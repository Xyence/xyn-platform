import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ApplicationArtifactMembership, ApplicationDetail, ApplicationSummary, SolutionChangeSession, UnifiedArtifact } from "../../../api/types";
import {
  createSolutionChangeSession,
  generateSolutionChangePlan,
  getApplication,
  listApplications,
  listArtifacts,
  listApplicationArtifactMemberships,
  listSolutionChangeSessions,
  prepareSolutionChangePreview,
  stageSolutionChangeApply,
  updateSolutionChangeSession,
  upsertApplicationArtifactMembership,
  validateSolutionChangeSession,
} from "../../../api/xyn";
import type { ConsolePanelKey } from "../console/WorkbenchPanelHost";
import WorkspaceUnavailableState, { classifyWorkspaceUnavailableReason } from "../common/WorkspaceUnavailableState";

const ROLE_OPTIONS: ApplicationArtifactMembership["role"][] = [
  "primary_ui",
  "primary_api",
  "integration_adapter",
  "worker",
  "runtime_service",
  "shared_library",
  "supporting",
];

type OpenPanel = (
  panelKey: ConsolePanelKey,
  params?: Record<string, unknown>,
  options?: { open_in?: "current_panel" | "new_panel" | "side_by_side"; return_to_panel_id?: string }
) => void;

export function SolutionListPanel({
  workspaceId,
  workspaceName,
  solutionNameQuery,
  onOpenPanel,
}: {
  workspaceId: string;
  workspaceName: string;
  solutionNameQuery?: string;
  onOpenPanel: OpenPanel;
}) {
  const [items, setItems] = useState<ApplicationSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [autoOpened, setAutoOpened] = useState<boolean>(false);

  useEffect(() => {
    let ignore = false;
    async function run() {
      if (!workspaceId) {
        setItems([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      try {
        const payload = await listApplications(workspaceId);
        if (!ignore) setItems(payload.applications || []);
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "Failed to load solutions.");
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [workspaceId]);

  const sorted = useMemo(
    () => [...items].sort((a, b) => (a.updated_at > b.updated_at ? -1 : 1)),
    [items]
  );

  useEffect(() => {
    const query = String(solutionNameQuery || "").trim().toLowerCase();
    if (!query || loading || autoOpened) return;
    const exact = sorted.find((item) => String(item.name || "").trim().toLowerCase() === query);
    const fuzzy = sorted.find((item) => String(item.name || "").trim().toLowerCase().includes(query));
    const target = exact || fuzzy;
    if (!target) return;
    setAutoOpened(true);
    onOpenPanel("solution_detail", { application_id: target.id }, { open_in: "new_panel" });
  }, [solutionNameQuery, loading, autoOpened, sorted, onOpenPanel]);

  return (
    <section className="card stack" data-testid="solution-list-panel">
      <h3>Solutions</h3>
      <p className="muted">
        Multi-artifact development groups for <strong>{workspaceName || "this workspace"}</strong>.
      </p>
      {loading ? <p className="muted">Loading solutions…</p> : null}
      {!loading && error ? <p className="danger">{error}</p> : null}
      {!loading && !error && sorted.length === 0 ? <p className="muted">No solutions have been registered yet.</p> : null}
      {!loading && !error && sorted.length > 0 ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Goals</th>
                <th>Artifacts</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <tr key={item.id}>
                  <td>{item.name}</td>
                  <td>{item.status}</td>
                  <td>{item.goal_count || 0}</td>
                  <td>{item.artifact_member_count || 0}</td>
                  <td>{item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}</td>
                  <td>
                    <button
                      className="ghost sm"
                      type="button"
                      onClick={() => onOpenPanel("solution_detail", { application_id: item.id }, { open_in: "new_panel" })}
                    >
                      Open
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

export function SolutionDetailPanel({
  workspaceId,
  applicationId,
  onOpenPanel,
}: {
  workspaceId: string;
  applicationId: string;
  onOpenPanel: OpenPanel;
}) {
  const [application, setApplication] = useState<ApplicationDetail | null>(null);
  const [memberships, setMemberships] = useState<ApplicationArtifactMembership[]>([]);
  const [artifacts, setArtifacts] = useState<UnifiedArtifact[]>([]);
  const [sessions, setSessions] = useState<SolutionChangeSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string>("");
  const [selectedArtifactIds, setSelectedArtifactIds] = useState<string[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [unavailableReason, setUnavailableReason] = useState<"not_found" | "access_denied" | null>(null);
  const [artifactId, setArtifactId] = useState<string>("");
  const [artifactScopeMode, setArtifactScopeMode] = useState<"solution" | "all">("solution");
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
        setApplication(null);
        setMemberships([]);
        setArtifacts([]);
        setSessions([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      setError("");
      setUnavailableReason(null);
      try {
        const artifactParams = artifactScopeMode === "solution" ? { limit: 200, scope: "solution" as const } : { limit: 200 };
        const app = await getApplication(applicationId);
        if (ignore) return;
        if (app.workspace_id && workspaceId && String(app.workspace_id) !== String(workspaceId)) {
          setApplication(null);
          setMemberships([]);
          setArtifacts([]);
          setSessions([]);
          setUnavailableReason("not_found");
          return;
        }
        const [memberPayload, artifactPayload, sessionPayload] = await Promise.all([
          listApplicationArtifactMemberships(applicationId),
          listArtifacts(artifactParams),
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
        if (!ignore) {
          const message = err instanceof Error ? err.message : "Failed to load solution detail.";
          const reason = classifyWorkspaceUnavailableReason(message);
          if (reason === "not_found" || reason === "access_denied") {
            setUnavailableReason(reason);
            setError("");
            return;
          }
          setError(message);
        }
      } finally {
        if (!ignore) setLoading(false);
      }
    }
    void run();
    return () => {
      ignore = true;
    };
  }, [applicationId, artifactScopeMode]);

  const activeSession = useMemo(
    () => sessions.find((item) => item.id === activeSessionId) || null,
    [activeSessionId, sessions]
  );

  if (loading) {
    return (
      <section className="card stack">
        <h3>Solution</h3>
        <p className="muted">Loading solution…</p>
      </section>
    );
  }

  if (unavailableReason || !application) {
    return (
      <WorkspaceUnavailableState
        itemLabel="Solution"
        workspaceLabel={workspaceId || "this workspace"}
        reason={unavailableReason || "not_found"}
        onOpenList={() => onOpenPanel("solution_list", { workspace_id: workspaceId }, { open_in: "current_panel" })}
        openListLabel="Open Solutions"
      />
    );
  }

  if (error) {
    return (
      <section className="card stack">
        <h3>Solution</h3>
        <p className="danger">{error}</p>
      </section>
    );
  }

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
  const sessionBuild = (previewState?.session_build as Record<string, unknown> | undefined) || {};
  const launchedContainers = (sessionBuild?.launched_containers as unknown[] | undefined) || [];
  const builtForSession =
    Boolean(previewState?.newly_built_for_session) &&
    String(sessionBuild?.status || "").toLowerCase() === "succeeded" &&
    launchedContainers.length > 0;
  const reusedRuntime = !builtForSession;
  const validationState = (activeSession?.validation as Record<string, unknown> | undefined) || {};
  const validationChecks = (validationState?.checks as Array<Record<string, unknown>> | undefined) || [];

  return (
    <div className="stack" data-testid="solution-detail-panel">
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
          <div>
            <h3>{application?.name || "Solution"}</h3>
            <p className="muted">{application?.summary || "Application-level development context across member artifacts."}</p>
          </div>
          <div className="inline-action-row">
            <button
              className="ghost sm"
              type="button"
              onClick={() =>
                onOpenPanel(
                  "composer_detail",
                  {
                    workspace_id: workspaceId,
                    application_id: applicationId,
                    ...(activeSessionId ? { solution_change_session_id: activeSessionId } : {}),
                  },
                  { open_in: "new_panel" }
                )}
            >
              Open Composer
            </button>
            <button className="ghost sm" type="button" onClick={() => onOpenPanel("solution_list", { workspace_id: workspaceId })}>
              Back to Solutions
            </button>
          </div>
        </div>
      </section>
      <section className="card">
        <h4>Artifact Membership</h4>
        <p className="muted">Assigned artifacts and their solution roles.</p>
        {memberships.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Artifact</th>
                  <th>Role</th>
                  <th>Responsibility</th>
                </tr>
              </thead>
              <tbody>
                {memberships.map((item) => (
                  <tr key={item.id}>
                    <td>{item.artifact?.title || item.artifact_id}</td>
                    <td>{item.role}</td>
                    <td>{item.responsibility_summary || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No artifacts assigned yet.</p>
        )}
      </section>

      <section className="card">
        <h4>New Change Session</h4>
        <p className="muted">Describe the solution-level change request. Xyn will analyze likely impacted artifacts and create a coordinated planning session.</p>
        <form className="stack" onSubmit={(event) => void handleCreateSession(event)}>
          <label className="field">
            <span className="field-label">Title (optional)</span>
            <input aria-label="Title" type="text" value={changeTitle} onChange={(event) => setChangeTitle(event.target.value)} placeholder="Campaign monitoring enhancement" />
          </label>
          <label className="field">
            <span className="field-label">Requested change</span>
            <textarea
              aria-label="Requested change"
              rows={4}
              value={changeRequest}
              onChange={(event) => setChangeRequest(event.target.value)}
              placeholder="Describe the cross-artifact change request."
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
        <h4>Change Sessions</h4>
        {sessions.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Session</th>
                  <th>Status</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {sessions.map((session) => (
                  <tr key={session.id}>
                    <td>{session.title}</td>
                    <td>{session.status}</td>
                    <td>{session.updated_at ? new Date(session.updated_at).toLocaleString() : "—"}</td>
                    <td>
                      <button
                        className={`ghost sm ${activeSessionId === session.id ? "active" : ""}`}
                        type="button"
                        onClick={() => {
                          setActiveSessionId(session.id);
                          setSelectedArtifactIds(session.selected_artifact_ids || []);
                        }}
                      >
                        {activeSessionId === session.id ? "Selected" : "Select"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">No change sessions yet.</p>
        )}
      </section>

      {activeSession ? (
        <section className="card stack">
          <h4>Selected Session</h4>
          <p className="muted">
            <strong>{activeSession.title}</strong> · {activeSession.status}
          </p>
          <div className="field-label">Impacted Artifact Selection</div>
          {impactedRows.length ? (
            <div className="stack">
              {impactedRows.map((row, index) => {
                const artifactIdValue = String(row.artifact_id || "");
                const checked = selectedArtifactIds.includes(artifactIdValue);
                return (
                  <label key={`${artifactIdValue}-${index}`} className="row" style={{ alignItems: "flex-start", gap: 8 }}>
                    <input type="checkbox" checked={checked} onChange={(event) => toggleArtifactSelection(artifactIdValue, event.target.checked)} />
                    <span>
                      <strong>{String(row.artifact_title || artifactIdValue || "Artifact")}</strong> ({String(row.role || "supporting")}){" "}
                      <span className="muted">score {String(row.score || "0")}</span>
                      <br />
                      <span className="muted">{Array.isArray(row.reasons) ? row.reasons.map((entry) => String(entry)).join("; ") : ""}</span>
                    </span>
                  </label>
                );
              })}
            </div>
          ) : (
            <p className="muted">No impacted artifact analysis available yet.</p>
          )}
          <div className="inline-action-row">
            <button className="ghost sm" type="button" onClick={() => void handleSaveImpactedArtifacts()} disabled={saving}>
              {saving ? "Saving…" : "Save Impacted Artifacts"}
            </button>
            <button className="ghost sm" type="button" onClick={() => void handleGeneratePlan()} disabled={planningSession}>
              {planningSession ? "Planning…" : "Generate Cross-Artifact Plan"}
            </button>
            <button className="ghost sm" type="button" onClick={() => void handleStageApply()} disabled={stagingSession}>
              {stagingSession ? "Staging…" : "Stage Coordinated Apply"}
            </button>
            <button className="ghost sm" type="button" onClick={() => void handlePreparePreview()} disabled={preparingPreview}>
              {preparingPreview ? "Preparing…" : "Prepare Preview Handoff"}
            </button>
            <button className="ghost sm" type="button" onClick={() => void handleValidateSession()} disabled={validatingSession}>
              {validatingSession ? "Validating…" : "Run Validation"}
            </button>
            <button
              className="ghost sm"
              type="button"
              onClick={() =>
                onOpenPanel(
                  "composer_detail",
                  {
                    workspace_id: workspaceId,
                    application_id: applicationId,
                    solution_change_session_id: activeSessionId,
                  },
                  { open_in: "new_panel" }
                )}
            >
              Open Session In Composer
            </button>
          </div>

          {Object.keys(activePlan).length > 0 ? (
            <>
              <h5>Structured Plan</h5>
              <pre className="code-block">{JSON.stringify(activePlan, null, 2)}</pre>
            </>
          ) : null}

          {stagedArtifacts.length ? (
            <>
              <h5>Staged Multi-Artifact Apply State</h5>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Artifact</th>
                      <th>Role</th>
                      <th>State</th>
                      <th>Validation</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stagedArtifacts.map((row, index) => (
                      <tr key={`${String(row.artifact_id || "artifact")}-${index}`}>
                        <td>{String(row.artifact_title || row.artifact_id || "artifact")}</td>
                        <td>{String(row.role || "supporting")}</td>
                        <td>{String(row.state || row.apply_state || "pending")}</td>
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
            <section className="stack">
              <h5>Preview Orchestration</h5>
              <p className="muted">
                Status: {String(previewState.status || "unknown")} · Mode: {String(previewState.mode || "n/a")}
              </p>
              <p className="muted">
                Session preview build: {builtForSession ? "newly built/deployed for this session" : "reused existing runtime"}
              </p>
              <p className="muted">Prepared at: {String(previewState.prepared_at || "—")}</p>
              {builtForSession ? (
                <p className="muted">
                  Launch evidence: {launchedContainers.map((item) => String(item || "")).filter(Boolean).join(", ") || "containers not listed"}
                </p>
              ) : null}
              {Boolean(previewState?.newly_built_for_session) && !builtForSession ? (
                <p className="danger">Preview marked as session-built but concrete launch evidence is missing.</p>
              ) : null}
              {reusedRuntime && sessionBuild?.reason ? (
                <p className="muted">Reuse reason: {String(sessionBuild.reason)}</p>
              ) : null}
              {String(previewState.primary_url || "").trim() ? (
                <p>
                  Primary preview URL:{" "}
                  <a href={String(previewState.primary_url)} target="_blank" rel="noreferrer">
                    {String(previewState.primary_url)}
                  </a>
                </p>
              ) : null}
              {previewUrls.length ? (
                <div className="stack">
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
                </div>
              ) : null}
              {previewArtifacts.length ? (
                <div className="stack">
                  <div className="field-label">Per-artifact preview evidence</div>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Artifact</th>
                          <th>Status</th>
                          <th>Compose</th>
                          <th>Runtime URL</th>
                        </tr>
                      </thead>
                      <tbody>
                        {previewArtifacts.map((row, index) => (
                          <tr key={`${String(row.artifact_id || "artifact")}-${index}`}>
                            <td>{String(row.artifact_title || row.artifact_id || "artifact")}</td>
                            <td>{String(row.status || "unknown")}</td>
                            <td>{String(row.compose_project || "—")}</td>
                            <td>{String(row.runtime_base_url || row.public_url || "—")}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ) : null}
              {previewState.error && typeof previewState.error === "object" ? (
                <p className="danger">
                  Preview error: {String((previewState.error as Record<string, unknown>).reason || "unknown")} —{" "}
                  {String((previewState.error as Record<string, unknown>).details || "")}
                </p>
              ) : null}
            </section>
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
        <h4>Add Artifact Membership</h4>
        <p className="muted">Assign coordinated artifacts under this solution.</p>
        <form className="stack" onSubmit={(event) => void handleAddMembership(event)}>
          <label className="field">
            <span className="field-label">Candidate scope</span>
            <select
              aria-label="Candidate scope"
              value={artifactScopeMode}
              onChange={(event) => {
                setArtifactId("");
                setArtifactScopeMode(event.target.value === "all" ? "all" : "solution");
              }}
            >
              <option value="solution">Solution-scoped artifacts</option>
              <option value="all">All artifacts (include shared/platform)</option>
            </select>
          </label>
          <label className="field">
            <span className="field-label">Artifact</span>
            <select aria-label="Artifact" value={artifactId} onChange={(event) => setArtifactId(event.target.value)} required>
              <option value="">Select artifact…</option>
              {artifacts.map((artifact) => (
                <option key={artifact.id} value={artifact.id}>
                  {artifact.title} ({artifact.artifact_type})
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
