import { FormEvent, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { ApplicationArtifactMembership, ApplicationDetail, SolutionChangeSession, UnifiedArtifact } from "../../api/types";
import {
  createSolutionChangeSession,
  generateSolutionChangePlan,
  getApplication,
  listArtifacts,
  prepareSolutionChangePreview,
  stageSolutionChangeApply,
  validateSolutionChangeSession,
  listApplicationArtifactMemberships,
  listSolutionChangeSessions,
  updateSolutionChangeSession,
  upsertApplicationArtifactMembership,
} from "../../api/xyn";

const ROLE_OPTIONS: ApplicationArtifactMembership["role"][] = [
  "primary_ui",
  "primary_api",
  "integration_adapter",
  "worker",
  "runtime_service",
  "shared_library",
  "supporting",
];

type SolutionDetailPageProps = {
  workspaceId: string;
};

export default function SolutionDetailPage({ workspaceId }: SolutionDetailPageProps) {
  const params = useParams<{ applicationId: string }>();
  const applicationId = String(params.applicationId || "").trim();

  const [application, setApplication] = useState<ApplicationDetail | null>(null);
  const [memberships, setMemberships] = useState<ApplicationArtifactMembership[]>([]);
  const [artifacts, setArtifacts] = useState<UnifiedArtifact[]>([]);
  const [sessions, setSessions] = useState<SolutionChangeSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [artifactId, setArtifactId] = useState<string>("");
  const [role, setRole] = useState<ApplicationArtifactMembership["role"]>("supporting");
  const [responsibilitySummary, setResponsibilitySummary] = useState<string>("");
  const [saving, setSaving] = useState<boolean>(false);
  const [changeTitle, setChangeTitle] = useState<string>("");
  const [changeRequest, setChangeRequest] = useState<string>("");
  const [creatingSession, setCreatingSession] = useState<boolean>(false);
  const [planningSession, setPlanningSession] = useState<boolean>(false);
  const [stagingSession, setStagingSession] = useState<boolean>(false);
  const [preparingPreview, setPreparingPreview] = useState<boolean>(false);
  const [validatingSession, setValidatingSession] = useState<boolean>(false);

  async function refreshSessions() {
    if (!applicationId) return;
    const payload = await listSolutionChangeSessions(applicationId);
    const next = payload.sessions || [];
    setSessions(next);
    if (!activeSessionId && next.length > 0) {
      setActiveSessionId(next[0].id);
      setSelectedArtifactIds(next[0].selected_artifact_ids || []);
    }
  }

  useEffect(() => {
    let ignore = false;
    async function run() {
      if (!applicationId) {
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const [app, memberPayload, artifactPayload, sessionPayload] = await Promise.all([
          getApplication(applicationId),
          listApplicationArtifactMemberships(applicationId),
          listArtifacts({ limit: 200 }),
          listSolutionChangeSessions(applicationId),
        ]);
        if (ignore) return;
        setApplication(app);
        setMemberships(memberPayload.memberships || []);
        setArtifacts(artifactPayload.artifacts || []);
        const loadedSessions = sessionPayload.sessions || [];
        setSessions(loadedSessions);
        if (loadedSessions.length > 0) {
          setActiveSessionId(loadedSessions[0].id);
          setSelectedArtifactIds(loadedSessions[0].selected_artifact_ids || []);
        }
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "Failed to load solution detail.");
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [applicationId]);

  const activeSession = useMemo(
    () => sessions.find((item) => item.id === activeSessionId) || null,
    [activeSessionId, sessions]
  );

  const openComposerUrl = useMemo(() => {
    if (!workspaceId || !applicationId) return "";
    const query = new URLSearchParams();
    query.set("panel", "composer_detail");
    query.set("application_id", applicationId);
    if (activeSessionId) query.set("solution_change_session_id", activeSessionId);
    return `/w/${encodeURIComponent(workspaceId)}/workbench?${query.toString()}`;
  }, [workspaceId, applicationId, activeSessionId]);

  async function handleAddMembership(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!artifactId || !applicationId) return;
    setSaving(true);
    setError("");
    try {
      await upsertApplicationArtifactMembership(applicationId, {
        artifact_id: artifactId,
        role,
        responsibility_summary: responsibilitySummary,
      });
      const payload = await listApplicationArtifactMemberships(applicationId);
      setMemberships(payload.memberships || []);
      setArtifactId("");
      setRole("supporting");
      setResponsibilitySummary("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save membership.");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateSession(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!applicationId || !changeRequest.trim()) return;
    setCreatingSession(true);
    setError("");
    try {
      const response = await createSolutionChangeSession(applicationId, {
        title: changeTitle.trim() || undefined,
        request_text: changeRequest.trim(),
      });
      setChangeTitle("");
      setChangeRequest("");
      await refreshSessions();
      setActiveSessionId(response.session.id);
      setSelectedArtifactIds(response.session.selected_artifact_ids || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create change session.");
    } finally {
      setCreatingSession(false);
    }
  }

  async function handleSaveImpactedArtifacts() {
    if (!applicationId || !activeSessionId) return;
    setSaving(true);
    setError("");
    try {
      const updated = await updateSolutionChangeSession(applicationId, activeSessionId, {
        selected_artifact_ids: selectedArtifactIds,
      });
      await refreshSessions();
      setSelectedArtifactIds(updated.selected_artifact_ids || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update impacted artifacts.");
    } finally {
      setSaving(false);
    }
  }

  async function handleGeneratePlan() {
    if (!applicationId || !activeSessionId) return;
    setPlanningSession(true);
    setError("");
    try {
      const response = await generateSolutionChangePlan(applicationId, activeSessionId);
      await refreshSessions();
      setActiveSessionId(response.session.id);
      setSelectedArtifactIds(response.session.selected_artifact_ids || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate cross-artifact plan.");
    } finally {
      setPlanningSession(false);
    }
  }

  async function handleStageApply() {
    if (!applicationId || !activeSessionId) return;
    setStagingSession(true);
    setError("");
    try {
      await stageSolutionChangeApply(applicationId, activeSessionId);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to stage coordinated apply change.");
    } finally {
      setStagingSession(false);
    }
  }

  async function handlePreparePreview() {
    if (!applicationId || !activeSessionId) return;
    setPreparingPreview(true);
    setError("");
    try {
      await prepareSolutionChangePreview(applicationId, activeSessionId);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to prepare coordinated preview handoff.");
    } finally {
      setPreparingPreview(false);
    }
  }

  async function handleValidateSession() {
    if (!applicationId || !activeSessionId) return;
    setValidatingSession(true);
    setError("");
    try {
      await validateSolutionChangeSession(applicationId, activeSessionId);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to validate staged solution change.");
    } finally {
      setValidatingSession(false);
    }
  }

  function toggleArtifactSelection(artifactIdValue: string, checked: boolean) {
    setSelectedArtifactIds((prev) => {
      if (checked) return prev.includes(artifactIdValue) ? prev : [...prev, artifactIdValue];
      return prev.filter((item) => item !== artifactIdValue);
    });
  }

  const impactedRows = (activeSession?.analysis?.impacted_artifacts as Array<Record<string, unknown>> | undefined) || [];
  const activePlan = (activeSession?.plan as Record<string, unknown> | undefined) || {};
  const stagedChanges = (activeSession?.staged_changes as Record<string, unknown> | undefined) || {};
  const stagedArtifacts = (stagedChanges?.artifact_states as Array<Record<string, unknown>> | undefined) || [];
  const previewState = (activeSession?.preview as Record<string, unknown> | undefined) || {};
  const previewUrls = (previewState?.preview_urls as unknown[] | undefined)?.map((item) => String(item || "")).filter(Boolean) || [];
  const previewArtifacts = (previewState?.artifacts as Array<Record<string, unknown>> | undefined) || [];
  const validationState = (activeSession?.validation as Record<string, unknown> | undefined) || {};
  const validationChecks = (validationState?.checks as Array<Record<string, unknown>> | undefined) || [];

  return (
    <div className="stack">
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <div>
            <h2>{application?.name || "Solution"}</h2>
            <p className="muted">{application?.summary || "Application-level development context across member artifacts."}</p>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <Link className="ghost sm" to={`/w/${encodeURIComponent(workspaceId)}/solutions`}>
              Back
            </Link>
            {openComposerUrl ? (
              <Link className="button sm" to={openComposerUrl}>
                Open Composer
              </Link>
            ) : null}
          </div>
        </div>
      </section>

      <section className="card">
        {loading ? <p className="muted">Loading solution context…</p> : null}
        {!loading && error ? <p className="muted">{error}</p> : null}
        {!loading && !error ? (
          <>
            <h3>Member Artifacts</h3>
            {memberships.length === 0 ? (
              <p className="muted">No artifacts assigned yet.</p>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Artifact</th>
                      <th>Type</th>
                      <th>Role</th>
                      <th>Responsibility</th>
                    </tr>
                  </thead>
                  <tbody>
                    {memberships.map((member) => (
                      <tr key={member.id}>
                        <td>{member.artifact?.title || member.artifact_id}</td>
                        <td>{member.artifact?.type || "—"}</td>
                        <td>{member.role}</td>
                        <td>{member.responsibility_summary || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </section>

      <section className="card">
        <h3>Create Solution Change Session</h3>
        <p className="muted">Describe the solution-level change request. Xyn will analyze likely impacted artifacts and create a coordinated planning session.</p>
        <form className="stack" onSubmit={(event) => void handleCreateSession(event)}>
          <label className="field">
            <span className="field-label">Session title</span>
            <input
              aria-label="Session title"
              type="text"
              value={changeTitle}
              onChange={(event) => setChangeTitle(event.target.value)}
              placeholder="Optional concise title"
            />
          </label>
          <label className="field">
            <span className="field-label">Requested change</span>
            <textarea
              aria-label="Requested change"
              value={changeRequest}
              onChange={(event) => setChangeRequest(event.target.value)}
              rows={4}
              placeholder="Describe the solution-level change and expected behavior."
              required
            />
          </label>
          <div className="row">
            <button className="button sm" type="submit" disabled={creatingSession || !changeRequest.trim()}>
              {creatingSession ? "Creating…" : "Create Change Session"}
            </button>
          </div>
        </form>
      </section>

      <section className="card">
        <h3>Change Sessions</h3>
        {sessions.length === 0 ? (
          <p className="muted">No change sessions yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Impacted</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((session) => (
                  <tr key={session.id}>
                    <td>{session.title}</td>
                    <td>{session.status}</td>
                    <td>{session.selected_artifact_ids.length}</td>
                    <td>
                      <button
                        className="ghost sm"
                        type="button"
                        onClick={() => {
                          setActiveSessionId(session.id);
                          setSelectedArtifactIds(session.selected_artifact_ids || []);
                        }}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {activeSession ? (
        <section className="card">
          <h3>{activeSession.title}</h3>
          <p className="muted">{activeSession.request_text}</p>
          {impactedRows.length ? (
            <>
              <h4>Impacted Artifact Analysis</h4>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Include</th>
                      <th>Artifact</th>
                      <th>Role</th>
                      <th>Score</th>
                      <th>Reasoning</th>
                    </tr>
                  </thead>
                  <tbody>
                    {impactedRows.map((row) => {
                      const rowArtifactId = String(row.artifact_id || "");
                      const checked = selectedArtifactIds.includes(rowArtifactId);
                      const reasons = Array.isArray(row.reasons) ? row.reasons.map((item) => String(item)).join("; ") : "—";
                      return (
                        <tr key={String(row.membership_id || rowArtifactId)}>
                          <td>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => toggleArtifactSelection(rowArtifactId, event.target.checked)}
                            />
                          </td>
                          <td>{String(row.artifact_title || rowArtifactId)}</td>
                          <td>{String(row.role || "supporting")}</td>
                          <td>{String(row.score || "0")}</td>
                          <td>{reasons}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <button className="ghost sm" type="button" onClick={() => void handleSaveImpactedArtifacts()} disabled={saving}>
                  {saving ? "Saving…" : "Save Impacted Set"}
                </button>
                <button className="button sm" type="button" onClick={() => void handleGeneratePlan()} disabled={planningSession}>
                  {planningSession ? "Planning…" : "Generate Cross-Artifact Plan"}
                </button>
              </div>
            </>
          ) : null}

          {Object.keys(activePlan).length > 0 ? (
            <>
              <h4>Structured Plan</h4>
              <div className="detail-grid">
                <div>
                  <div className="field-label">Selected artifacts</div>
                  <div className="field-value">{Array.isArray(activePlan.selected_artifact_ids) ? activePlan.selected_artifact_ids.length : 0}</div>
                </div>
                <div>
                  <div className="field-label">Generated</div>
                  <div className="field-value">{String(activePlan.generated_at || "—")}</div>
                </div>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <button className="button sm" type="button" onClick={() => void handleStageApply()} disabled={stagingSession}>
                  {stagingSession ? "Staging…" : "Stage Coordinated Apply"}
                </button>
                <button className="ghost sm" type="button" onClick={() => void handlePreparePreview()} disabled={preparingPreview}>
                  {preparingPreview ? "Preparing…" : "Prepare Preview Handoff"}
                </button>
                <button className="ghost sm" type="button" onClick={() => void handleValidateSession()} disabled={validatingSession}>
                  {validatingSession ? "Validating…" : "Validate Staged Change"}
                </button>
              </div>
            </>
          ) : null}

          <h4>Execution Status</h4>
          <p className="muted">Session execution state: {activeSession.execution_status || "not_started"}</p>
          {stagedArtifacts.length ? (
            <>
              <h5>Staged Artifact Apply State</h5>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Artifact</th>
                      <th>Role</th>
                      <th>Apply State</th>
                      <th>Validation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stagedArtifacts.map((row, index) => (
                      <tr key={`${String(row.artifact_id || "artifact")}-${index}`}>
                        <td>{String(row.artifact_title || row.artifact_id || "—")}</td>
                        <td>{String(row.role || "supporting")}</td>
                        <td>{String(row.apply_state || row.state || "staged")}</td>
                        <td>{String(row.validation_state || "pending")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="muted">No staged artifacts yet.</p>
          )}

          {Object.keys(previewState).length > 0 ? (
            <>
              <h5>Preview Orchestration</h5>
              <p className="muted">
                Status: {String(previewState.status || "unknown")} · Mode: {String(previewState.mode || "n/a")}
              </p>
              <p className="muted">Prepared at: {String(previewState.prepared_at || "—")}</p>
              {String(previewState.primary_url || "").trim() ? (
                <p className="muted">
                  Primary preview URL:{" "}
                  <a href={String(previewState.primary_url)} target="_blank" rel="noreferrer">
                    {String(previewState.primary_url)}
                  </a>
                </p>
              ) : null}
              {previewUrls.length ? (
                <>
                  <div className="field-label">Preview URLs</div>
                  <ul>
                    {previewUrls.map((url) => (
                      <li key={url}>
                        <a href={url} target="_blank" rel="noreferrer">
                          {url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
              {previewArtifacts.length ? (
                <>
                  <div className="field-label">Per-artifact preview evidence</div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Artifact</th>
                          <th>Status</th>
                          <th>Compose Project</th>
                          <th>Runtime URL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {previewArtifacts.map((row, index) => (
                          <tr key={`${String(row.artifact_id || "artifact")}-${index}`}>
                            <td>{String(row.artifact_title || row.artifact_id || "—")}</td>
                            <td>{String(row.status || "unknown")}</td>
                            <td>{String(row.compose_project || "—")}</td>
                            <td>{String(row.runtime_base_url || "—")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
              {previewState.error && typeof previewState.error === "object" ? (
                <p className="muted">
                  Preview error: {String((previewState.error as Record<string, unknown>).reason || "unknown")} —{" "}
                  {String((previewState.error as Record<string, unknown>).details || "")}
                </p>
              ) : null}
            </>
          ) : null}

          {validationChecks.length ? (
            <>
              <h5>Validation/Test Status</h5>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Check</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {validationChecks.map((check, index) => (
                      <tr key={`${String(check.key || "check")}-${index}`}>
                        <td>{String(check.label || check.key || "check")}</td>
                        <td>{String(check.status || "unknown")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}
        </section>
      ) : null}

      <section className="card">
        <h3>Add Artifact Membership</h3>
        <p className="muted">Phase 1 assignment for grouping coordinated artifacts under this solution.</p>
        <form className="stack" onSubmit={(event) => void handleAddMembership(event)}>
          <label className="field">
            <span className="field-label">Artifact</span>
            <select aria-label="Artifact" value={artifactId} onChange={(event) => setArtifactId(event.target.value)} required>
              <option value="">Select artifact…</option>
              {artifacts.map((artifact) => (
                <option key={artifact.id} value={artifact.id}>
                  {artifact.title} ({artifact.type})
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Role</span>
            <select aria-label="Role" value={role} onChange={(event) => setRole(event.target.value as ApplicationArtifactMembership["role"])}>
              {ROLE_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span className="field-label">Responsibility</span>
            <input
              aria-label="Responsibility"
              type="text"
              value={responsibilitySummary}
              onChange={(event) => setResponsibilitySummary(event.target.value)}
              placeholder="Optional scope summary"
            />
          </label>
          <div className="row">
            <button className="button sm" type="submit" disabled={saving || !artifactId || !applicationId}>
              {saving ? "Saving…" : "Add Membership"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
