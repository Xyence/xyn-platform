import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import InlineMessage from "../../components/InlineMessage";
import { createWorkspaceMembership, listIdentities, listWorkspaceMemberships, updateWorkspaceMembership } from "../../api/xyn";
import type { IdentitySummary, WorkspaceMembershipSummary } from "../../api/types";
import { useNotifications } from "../state/notificationsStore";

const ROLE_OPTIONS = ["reader", "contributor", "publisher", "moderator", "admin"];

type AddMemberModalProps = {
  open: boolean;
  loading: boolean;
  identities: IdentitySummary[];
  onClose: () => void;
  onSubmit: (payload: { user_identity_id: string; role: string; termination_authority: boolean }) => Promise<void>;
  initialRole?: string;
  initialError?: string;
};

function AddMemberModal({ open, loading, identities, onClose, onSubmit, initialRole = "reader", initialError = "" }: AddMemberModalProps) {
  const identityRef = useRef<HTMLSelectElement | null>(null);
  const [identityId, setIdentityId] = useState("");
  const [role, setRole] = useState(initialRole);
  const [terminationAuthority, setTerminationAuthority] = useState(false);
  const [inlineError, setInlineError] = useState<string | null>(initialError || null);

  useEffect(() => {
    if (!open) return;
    setInlineError(initialError || null);
    setIdentityId("");
    setRole(initialRole);
    setTerminationAuthority(false);
    const timer = window.setTimeout(() => identityRef.current?.focus(), 0);
    return () => window.clearTimeout(timer);
  }, [initialError, initialRole, open]);

  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !loading) onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [loading, onClose, open]);

  if (!open) return null;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!identityId) {
      setInlineError("Identity is required.");
      return;
    }
    if (!role) {
      setInlineError("Role is required.");
      return;
    }
    setInlineError(null);
    try {
      await onSubmit({ user_identity_id: identityId, role, termination_authority: terminationAuthority });
    } catch (err) {
      const message = (err as Error).message || "Request failed.";
      if (/already.*member|duplicate/i.test(message)) {
        setInlineError("This identity is already a member of this workspace.");
      } else {
        setInlineError(message);
      }
    }
  };

  return (
    <div className="modal-backdrop" onClick={loading ? undefined : onClose}>
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-member-title"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 id="add-member-title">Add member</h3>
        <form onSubmit={(event) => void handleSubmit(event)}>
          <div className="form-grid">
            <label>
              Identity
              <select ref={identityRef} value={identityId} onChange={(event) => setIdentityId(event.target.value)} required>
                <option value="">Select identity</option>
                {identities.map((identity) => (
                  <option key={identity.id} value={identity.id}>
                    {identity.display_name || identity.email || identity.subject}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Role
              <select value={role} onChange={(event) => setRole(event.target.value)} required>
                {ROLE_OPTIONS.map((option) => (
                  <option key={option} value={option}>{option}</option>
                ))}
              </select>
            </label>
            <label>
              <span>Termination authority</span>
              <input
                type="checkbox"
                checked={terminationAuthority}
                onChange={(event) => setTerminationAuthority(event.target.checked)}
              />
            </label>
          </div>
          {inlineError ? <InlineMessage tone="error" title="Request failed" body={inlineError} /> : null}
          <div className="inline-actions" style={{ marginTop: 12 }}>
            <button className="primary" type="submit" disabled={loading || !identityId || !role}>
              {loading ? "Adding..." : "Add member"}
            </button>
            <button className="ghost" type="button" onClick={onClose} disabled={loading}>
              Cancel
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function PeopleRolesPage({ workspaceId, canAdmin }: { workspaceId: string; canAdmin: boolean }) {
  const { push } = useNotifications();
  const [memberships, setMemberships] = useState<WorkspaceMembershipSummary[]>([]);
  const [identities, setIdentities] = useState<IdentitySummary[]>([]);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const addMemberButtonRef = useRef<HTMLButtonElement | null>(null);
  const [loading, setLoading] = useState(false);
  const [pendingHighlightMembershipId, setPendingHighlightMembershipId] = useState<string>("");
  const [highlightedMembershipId, setHighlightedMembershipId] = useState<string>("");
  const rowRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!workspaceId) {
      setMemberships([]);
      return;
    }
    try {
      setError(null);
      const [membersData, identitiesData] = await Promise.all([
        listWorkspaceMemberships(workspaceId),
        listIdentities(),
      ]);
      setMemberships(membersData.memberships || []);
      setIdentities(identitiesData.identities || []);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [workspaceId]);

  useEffect(() => {
    void load();
  }, [load]);

  const availableIdentities = useMemo(
    () => identities.filter((id) => !memberships.some((m) => m.user_identity_id === id.id)),
    [identities, memberships]
  );

  useEffect(() => {
    if (!pendingHighlightMembershipId) return;
    const row = rowRefs.current[pendingHighlightMembershipId];
    if (!row) return;
    row.scrollIntoView({ behavior: "smooth", block: "center" });
    setHighlightedMembershipId(pendingHighlightMembershipId);
    setPendingHighlightMembershipId("");
    const timer = window.setTimeout(() => setHighlightedMembershipId(""), 1800);
    return () => window.clearTimeout(timer);
  }, [memberships, pendingHighlightMembershipId]);

  const closeAddMemberModal = useCallback(() => {
    setAddModalOpen(false);
    window.setTimeout(() => addMemberButtonRef.current?.focus(), 0);
  }, []);

  const addMember = async (payload: { user_identity_id: string; role: string; termination_authority: boolean }) => {
    if (!payload.user_identity_id) return;
    try {
      setLoading(true);
      const result = await createWorkspaceMembership(workspaceId, {
        user_identity_id: payload.user_identity_id,
        role: payload.role,
        termination_authority: payload.termination_authority,
      });
      await load();
      closeAddMemberModal();
      setPendingHighlightMembershipId(result.id || "");
      push({
        level: "success",
        title: "Member added",
        message: "Workspace membership created.",
      });
    } catch (err) {
      const message = (err as Error).message || "Request failed.";
      setError(message);
      push({ level: "error", title: "Add member failed", message });
      throw err;
    } finally {
      setLoading(false);
    }
  };

  const updateMember = async (membershipId: string, nextRole: string) => {
    try {
      await updateWorkspaceMembership(workspaceId, membershipId, { role: nextRole });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>People & Roles</h2>
          <p className="muted">Workspace role assignments and termination authority.</p>
          <p className="muted small">Workspace-scoped</p>
        </div>
        <div className="inline-actions">
          <button className="ghost" onClick={() => void load()} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh"}
          </button>
          {canAdmin ? (
            <button
              ref={addMemberButtonRef}
              className="primary"
              onClick={() => setAddModalOpen(true)}
              disabled={loading || availableIdentities.length === 0}
            >
              Add member
            </button>
          ) : null}
        </div>
      </div>
      {error && <InlineMessage tone="error" title="Request failed" body={error} />}
      <section className="card">
        <div className="card-header">
          <h3>Members</h3>
        </div>
        <div className="instance-list">
          {memberships.map((m) => (
            <div
              className={`instance-row ${highlightedMembershipId === m.id ? "active" : ""}`}
              key={m.id}
              ref={(node) => {
                rowRefs.current[m.id] = node;
              }}
            >
              <div>
                <strong>{m.display_name || m.email || m.user_identity_id}</strong>
                <span className="muted small">{m.email || ""}</span>
              </div>
              {canAdmin ? (
                <select value={m.role} onChange={(event) => updateMember(m.id, event.target.value)}>
                  {ROLE_OPTIONS.map((option) => (
                    <option key={option} value={option}>{option}</option>
                  ))}
                </select>
              ) : (
                <span className="muted small">{m.role}</span>
              )}
            </div>
          ))}
          {memberships.length === 0 && <p className="muted">No members in workspace.</p>}
        </div>
      </section>
      <AddMemberModal
        open={addModalOpen}
        loading={loading}
        identities={availableIdentities}
        onClose={closeAddMemberModal}
        onSubmit={addMember}
      />
    </>
  );
}
