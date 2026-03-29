import { FormEvent, useEffect, useMemo, useState } from "react";
import type { ApplicationArtifactMembership, ApplicationDetail, ApplicationSummary, SolutionChangeSession, UnifiedArtifact } from "../../../api/types";
import {
  activateApplication,
  applyApplicationPlan,
  createSolutionChangeSession,
  deleteSolutionChangeSession,
  generateApplicationPlan,
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

const WORKSTREAM_LABELS: Record<string, string> = {
  ui: "UI / presentation",
  api: "API / service",
  data: "Data / storage",
  workflow: "Workflow / orchestration",
  validation: "Validation / verification",
  behavior: "Behavior / interaction logic",
};

function workstreamLabel(value: string): string {
  const token = String(value || "").trim().toLowerCase();
  return WORKSTREAM_LABELS[token] || token;
}

export function SolutionListPanel({
  workspaceId,
  workspaceName,
  solutionNameQuery,
  createSolutionObjective,
  createSolutionName,
  onOpenPanel,
}: {
  workspaceId: string;
  workspaceName: string;
  solutionNameQuery?: string;
  createSolutionObjective?: string;
  createSolutionName?: string;
  onOpenPanel: OpenPanel;
}) {
  const [items, setItems] = useState<ApplicationSummary[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string>("");
  const [autoOpened, setAutoOpened] = useState<boolean>(false);
  const [createOpen, setCreateOpen] = useState<boolean>(false);
  const [createName, setCreateName] = useState<string>("");
  const [createObjective, setCreateObjective] = useState<string>("");
  const [creating, setCreating] = useState<boolean>(false);
  const [createError, setCreateError] = useState<string>("");

  async function loadSolutions() {
    if (!workspaceId) {
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const payload = await listApplications(workspaceId);
      setItems(payload.applications || []);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let ignore = false;
    async function run() {
      try {
        await loadSolutions();
      } catch (err) {
        if (!ignore) setError(err instanceof Error ? err.message : "Failed to load solutions.");
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

  useEffect(() => {
    const objective = String(createSolutionObjective || "").trim();
    if (!objective) return;
    setCreateOpen(true);
    setCreateObjective(objective);
    setCreateName(String(createSolutionName || "").trim());
  }, [createSolutionName, createSolutionObjective]);

  async function handleCreateSolution(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const objective = createObjective.trim();
    if (!workspaceId || !objective) return;
    setCreating(true);
    setCreateError("");
    try {
      const plan = await generateApplicationPlan({
        workspace_id: workspaceId,
        objective,
        ...(createName.trim() ? { application_name: createName.trim() } : {}),
      });
      const applied = await applyApplicationPlan(String(plan.id));
      const session = await createSolutionChangeSession(String(applied.application.id), {
        request_text: objective,
      });
      await loadSolutions();
      setCreateOpen(false);
      setCreateName("");
      setCreateObjective("");
      onOpenPanel(
        "composer_detail",
        {
          workspace_id: workspaceId,
          application_id: applied.application.id,
          solution_change_session_id: session.session.id,
        },
        { open_in: "new_panel" }
      );
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create solution.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <section className="card solution-list-card" data-testid="solution-list-panel">
      <div className="solution-list-header">
        <div>
          <h3>Solutions</h3>
          <p className="muted">
            Multi-artifact development groups for <strong>{workspaceName || "this workspace"}</strong>.
          </p>
        </div>
        <button className="button sm" type="button" onClick={() => {
          setCreateError("");
          setCreateOpen((current) => !current);
        }}>
          {createOpen ? "Close" : "New Solution"}
        </button>
      </div>
      {createOpen ? (
        <section className="card solution-create-card">
          <form className="stack" onSubmit={(event) => void handleCreateSolution(event)}>
            <label className="field">
              <span className="field-label">Solution name (optional)</span>
              <input
                aria-label="Solution name"
                type="text"
                value={createName}
                onChange={(event) => setCreateName(event.target.value)}
                placeholder="Deal Finder"
              />
            </label>
            <label className="field">
              <span className="field-label">Objective / request</span>
              <textarea
                aria-label="Objective / request"
                rows={3}
                value={createObjective}
                onChange={(event) => setCreateObjective(event.target.value)}
                placeholder="Describe the change you want planned."
                required
              />
            </label>
            {createError ? <p className="danger">{createError}</p> : null}
            <div className="inline-action-row">
              <button className="button sm" type="submit" disabled={creating || !createObjective.trim()}>
                {creating ? "Creating…" : "Create Solution"}
              </button>
            </div>
          </form>
        </section>
      ) : null}
      {loading ? <p className="muted">Loading solutions…</p> : null}
      {!loading && error ? <p className="danger">{error}</p> : null}
      {!loading && !error && sorted.length === 0 ? <p className="muted">No solutions have been registered yet.</p> : null}
      {!loading && !error && sorted.length > 0 ? (
        <div className="table-wrap solution-list-table-wrap">
          <table className="solution-list-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Status</th>
                <th>Goals</th>
                <th>Artifacts</th>
                <th>Updated</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((item) => (
                <tr key={item.id}>
                  <td className="solution-list-name-cell" title={item.name || ""}>{item.name}</td>
                  <td>{item.status}</td>
                  <td className="solution-list-quiet-count">{item.goal_count || 0}</td>
                  <td className="solution-list-quiet-count">{item.artifact_member_count || 0}</td>
                  <td className="solution-list-updated-cell">{item.updated_at ? new Date(item.updated_at).toLocaleString() : "—"}</td>
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
  const [deletingSessionId, setDeletingSessionId] = useState<string>("");
  const [selectedWorkstreams, setSelectedWorkstreams] = useState<string[]>([]);
  const [planningSession, setPlanningSession] = useState<boolean>(false);
  const [stagingSession, setStagingSession] = useState<boolean>(false);
  const [preparingPreview, setPreparingPreview] = useState<boolean>(false);
  const [validatingSession, setValidatingSession] = useState<boolean>(false);
  const [activationBusy, setActivationBusy] = useState<boolean>(false);
  const [activationFeedback, setActivationFeedback] = useState<{ tone: "info" | "warn" | "error"; title: string; body?: string } | null>(null);

  async function refreshSessions(preferredSessionId?: string | null) {
    if (!applicationId) return;
    const payload = await listSolutionChangeSessions(applicationId);
    const next = payload.sessions || [];
    setSessions(next);
    if (!next.length) {
      setActiveSessionId("");
      setSelectedArtifactIds([]);
      setSelectedWorkstreams([]);
      return;
    }
    const preferred =
      (preferredSessionId ? next.find((item) => item.id === preferredSessionId) : null) ||
      (activeSessionId ? next.find((item) => item.id === activeSessionId) : null) ||
      next[0];
    setActiveSessionId(preferred.id);
    setSelectedArtifactIds(preferred.selected_artifact_ids || []);
    setSelectedWorkstreams(preferred.confirmed_workstreams || []);
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
          setSelectedWorkstreams(loadedSessions[0].confirmed_workstreams || []);
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
      await refreshSessions(response.session.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create change session.");
    } finally {
      setCreatingSession(false);
    }
  }

  async function handleDeleteSession(session: SolutionChangeSession) {
    if (!applicationId) return;
    const confirmed = window.confirm(`Delete change session "${session.title}"? This cannot be undone.`);
    if (!confirmed) return;
    setDeletingSessionId(session.id);
    setError("");
    try {
      await deleteSolutionChangeSession(applicationId, session.id);
      const nextPreferred = activeSessionId === session.id ? null : activeSessionId;
      await refreshSessions(nextPreferred);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete change session.");
    } finally {
      setDeletingSessionId("");
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
      setSelectedWorkstreams(updated.confirmed_workstreams || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update impacted artifacts.");
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirmSuggestedFocus() {
    if (!applicationId || !activeSessionId) return;
    setSaving(true);
    setError("");
    try {
      const updated = await updateSolutionChangeSession(applicationId, activeSessionId, {
        confirmed_workstreams: selectedWorkstreams,
      });
      await refreshSessions();
      setSelectedArtifactIds(updated.selected_artifact_ids || []);
      setSelectedWorkstreams(updated.confirmed_workstreams || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to confirm suggested workstreams.");
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
      setSelectedWorkstreams(response.session.confirmed_workstreams || []);
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

  function resolveRuntimeTargetUrl(runtimeTarget: Record<string, unknown>, runtimeInstance: Record<string, unknown>): string {
    const candidates = [
      String(runtimeTarget.runtime_url || "").trim(),
      String(runtimeTarget.app_url || "").trim(),
      String(runtimeTarget.public_app_url || "").trim(),
      String(runtimeTarget.url || "").trim(),
      String(runtimeTarget.fqdn || "").trim(),
      String(runtimeInstance.fqdn || "").trim(),
    ].filter(Boolean);
    const first = candidates[0] || "";
    if (!first) return "";
    if (/^https?:\/\//i.test(first)) return first;
    if (/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(first)) return `https://${first}`;
    return "";
  }

  async function handleActivateSolution() {
    if (!applicationId || activationBusy) return;
    setActivationBusy(true);
    setActivationFeedback(null);
    try {
      const response = await activateApplication(applicationId);
      const runtimeTarget = response.runtime_target && typeof response.runtime_target === "object" ? response.runtime_target : {};
      const runtimeInstance = response.runtime_instance && typeof response.runtime_instance === "object" ? response.runtime_instance : {};
      const binding = response.solution_runtime_binding && typeof response.solution_runtime_binding === "object" ? response.solution_runtime_binding : {};
      const mode = String((binding as Record<string, unknown>).activation_mode || response.policy_source || "reconstructed");
      const modeLabel = mode === "composed" ? "composed" : "reconstructed";
      const composition = response.solution_activation_composition && typeof response.solution_activation_composition === "object"
        ? response.solution_activation_composition
        : {};
      const primarySlug = String(
        ((composition as Record<string, unknown>).primary_app_artifact_ref as Record<string, unknown> | undefined)?.artifact_slug || ""
      ).trim();
      const policySlug = String(
        ((composition as Record<string, unknown>).policy_artifact_ref as Record<string, unknown> | undefined)?.artifact_slug || ""
      ).trim();
      const compositionLabel = `Primary ${primarySlug || "—"} · Policy ${policySlug || "none"} · Mode ${modeLabel}`;

      if (response.status === "reused") {
        const target = resolveRuntimeTargetUrl(runtimeTarget as Record<string, unknown>, runtimeInstance as Record<string, unknown>);
        if (target) {
          window.open(target, "_blank", "noopener,noreferrer");
          setActivationFeedback({ tone: "info", title: `Opened existing dev sibling runtime (${modeLabel}).`, body: `${compositionLabel} · ${target}` });
        } else {
          setActivationFeedback({
            tone: "info",
            title: `Reused existing dev sibling runtime (${modeLabel}).`,
            body: `${compositionLabel} · Runtime target is active, but no openable URL was returned.`,
          });
        }
        return;
      }
      if (response.status === "queued_existing") {
        const draftId = String(response.activation?.draft_id || response.in_flight?.draft_id || "").trim();
        const jobId = String(response.activation?.job_id || response.in_flight?.job_id || "").trim();
        setActivationFeedback({
          tone: "info",
          title: `Solution activation already in progress (${modeLabel}).`,
          body: `${compositionLabel} · Draft ${draftId || "—"} · Job ${jobId || "—"}`,
        });
        return;
      }
      const draftId = String(response.activation?.draft_id || "").trim();
      const jobId = String(response.activation?.job_id || "").trim();
      setActivationFeedback({
        tone: "info",
        title: `Solution activation queued (${modeLabel}).`,
        body: `${compositionLabel} · Draft ${draftId || "—"} · Job ${jobId || "—"}`,
      });
    } catch (err) {
      setActivationFeedback({
        tone: "error",
        title: "Failed to open solution in dev sibling.",
        body: err instanceof Error ? err.message : "Request failed",
      });
    } finally {
      setActivationBusy(false);
    }
  }

  function toggleArtifactSelection(artifactIdValue: string, checked: boolean) {
    setSelectedArtifactIds((prev) => {
      if (checked) return prev.includes(artifactIdValue) ? prev : [...prev, artifactIdValue];
      return prev.filter((item) => item !== artifactIdValue);
    });
  }

  function toggleWorkstreamSelection(workstream: string, checked: boolean) {
    const token = String(workstream || "").trim().toLowerCase();
    if (!token) return;
    setSelectedWorkstreams((prev) => {
      if (checked) return prev.includes(token) ? prev : [...prev, token];
      return prev.filter((item) => item !== token);
    });
  }

  const analysisState = (activeSession?.analysis as Record<string, unknown> | undefined) || {};
  const impactedRows = (analysisState?.impacted_artifacts as Array<Record<string, unknown>> | undefined) || [];
  const suggestedWorkstreams = (analysisState?.suggested_workstreams as unknown[] | undefined)?.map((item) => String(item || "").trim()).filter(Boolean) || [];
  const confirmedWorkstreams = (activeSession?.confirmed_workstreams || []).map((item) => String(item || "").trim().toLowerCase()).filter(Boolean);
  const analysisStatus = String(analysisState?.analysis_status || "").toLowerCase();
  const analysisRan = Boolean(analysisState?.analyzed_at) || analysisStatus === "no_confident_matches";
  const analysisHasNoConfidentMatches = analysisRan && !impactedRows.length && !suggestedWorkstreams.length;
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
  const hasImpactedAnalysis = impactedRows.length > 0 || suggestedWorkstreams.length > 0 || analysisHasNoConfidentMatches;
  const hasSelectedArtifacts = selectedArtifactIds.length > 0;
  const hasConfirmedWorkstreamFocus = confirmedWorkstreams.length > 0;
  const hasReviewedArtifactFocus = hasSelectedArtifacts || hasConfirmedWorkstreamFocus || analysisHasNoConfidentMatches;
  const hasPlan = Object.keys(activePlan).length > 0;
  const executionStatus = String(activeSession?.execution_status || "").toLowerCase();
  const hasStagedArtifacts = stagedArtifacts.length > 0 || ["staged", "preview_ready", "validated"].includes(executionStatus);
  const hasPreviewEvidence = Object.keys(previewState).length > 0;
  const hasValidationEvidence = validationChecks.length > 0 || executionStatus === "validated";
  const planRequestText = String(activePlan.request_text || activeSession?.request_text || "—");
  const planSharedContracts = (activePlan.shared_contracts as unknown[] | undefined)?.map((item) => String(item || "").trim()).filter(Boolean) || [];
  const planImplementationSteps = (activePlan.implementation_steps as unknown[] | undefined)?.map((item) => String(item || "").trim()).filter(Boolean) || [];
  const planValidationSteps = (activePlan.validation_plan as unknown[] | undefined)?.map((item) => String(item || "").trim()).filter(Boolean) || [];

  const planningState = (activeSession?.planning as Record<string, unknown> | undefined) || {};
  const pendingCheckpoints = Array.isArray(planningState?.pending_checkpoints)
    ? (planningState.pending_checkpoints as Array<Record<string, unknown>>)
    : [];
  const hasPendingApproval = pendingCheckpoints.some(
    (checkpoint) =>
      String(checkpoint?.status || "").toLowerCase() === "pending" &&
      (String(checkpoint?.required_before || "").toLowerCase() === "stage" ||
        String(checkpoint?.required_before || "").toLowerCase() === "apply" ||
        String(checkpoint?.required_before || "").toLowerCase() === "dispatch")
  );

  type SessionStepKey = "analyze" | "save" | "plan" | "approve" | "stage" | "preview" | "validate" | "done";
  const nextStep: SessionStepKey =
    !activeSession ? "done" :
    !hasImpactedAnalysis ? "analyze" :
    !hasReviewedArtifactFocus ? "save" :
    !hasPlan ? "plan" :
    hasPendingApproval ? "approve" :
    !hasStagedArtifacts ? "stage" :
    !hasPreviewEvidence ? "preview" :
    !hasValidationEvidence ? "validate" :
    "done";

  const stageRows: Array<{ key: SessionStepKey; label: string; complete: boolean }> = [
    { key: "plan", label: "Plan ready", complete: hasPlan },
    { key: "analyze", label: "Analyze impacted artifacts", complete: hasImpactedAnalysis },
    { key: "save", label: "Review/save impacted focus", complete: hasReviewedArtifactFocus },
    { key: "approve", label: "Review/approve plan", complete: hasPlan && !hasPendingApproval },
    { key: "stage", label: "Stage apply", complete: hasStagedArtifacts },
    { key: "preview", label: "Preview", complete: hasPreviewEvidence },
    { key: "validate", label: "Validate", complete: hasValidationEvidence },
  ];
  const currentStageRow = stageRows.find((row) => row.key === nextStep);
  const nextStepCopy =
    nextStep === "analyze"
      ? "Next step: analyze impacted artifacts for this change session."
      : nextStep === "save"
      ? impactedRows.length
        ? "Next step: review and save impacted artifacts for planning."
        : "Next step: confirm suggested workstream focus for planning."
      : nextStep === "plan"
      ? "Next step: generate the structured change plan."
      : nextStep === "approve"
      ? "Planning approval is still required before staging. Open this session in Composer to review and approve the plan."
      : nextStep === "stage"
      ? "Next step: stage coordinated apply for the approved plan."
      : nextStep === "preview"
      ? "Next step: prepare preview to verify the staged change."
      : nextStep === "validate"
      ? "Next step: run validation checks on the prepared preview."
      : "Workflow complete: plan, stage, preview, and validation are all available.";

  const canStageApply = hasPlan && (hasSelectedArtifacts || hasConfirmedWorkstreamFocus) && !hasPendingApproval;
  const canPreparePreview = hasStagedArtifacts && !hasPendingApproval;
  const canValidateSession = hasStagedArtifacts && hasPreviewEvidence && !hasPendingApproval;
  const stageBlockedReason = hasPendingApproval
    ? "Blocked: planning approval is still pending. Open this session in Composer to approve the plan first."
    : !canStageApply
    ? "Blocked: confirm impacted artifact focus before staging."
    : "";
  const previewBlockedReason = hasPendingApproval
    ? "Blocked: planning approval is still pending."
    : !canPreparePreview
    ? "Blocked: stage coordinated apply first."
    : "";
  const validateBlockedReason = hasPendingApproval
    ? "Blocked: planning approval is still pending."
    : !canValidateSession
    ? "Blocked: prepare preview before validation."
    : "";

  return (
    <div className="solution-detail-layout" data-testid="solution-detail-panel">
      <section className="card solution-summary-card">
        <div className="solution-summary-header-row">
          <h3>{application?.name || "Solution"}</h3>
          <div className="inline-action-row">
            <button
              className="button sm"
              type="button"
              disabled={activationBusy}
              onClick={() => void handleActivateSolution()}
            >
              {activationBusy ? "Activating…" : "Open in Dev"}
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
        {application?.summary ? <p className="muted">{application.summary}</p> : null}
        <div className="solution-summary-metrics">
          <div>
            <span className="field-label">Status</span>
            <span className="field-value">{application?.status || "—"}</span>
          </div>
          <div>
            <span className="field-label">Updated</span>
            <span className="field-value">{application?.updated_at ? new Date(application.updated_at).toLocaleString() : "—"}</span>
          </div>
          <div>
            <span className="field-label">Goals</span>
            <span className="field-value">{application?.goal_count || 0}</span>
          </div>
          <div>
            <span className="field-label">Artifacts</span>
            <span className="field-value">{application?.artifact_member_count || memberships.length || 0}</span>
          </div>
        </div>
        {activationFeedback ? (
          <p className={`${activationFeedback.tone === "error" ? "danger" : "muted"} small`}>
            <strong>{activationFeedback.title}</strong>
            {activationFeedback.body ? ` ${activationFeedback.body}` : ""}
          </p>
        ) : null}
        <p className="muted small">
          Activation mode:{" "}
          <strong>{String(application.runtime_binding?.activation_mode || "reconstructed")}</strong>
          {" · "}
          Freshness: <strong>{String(application.runtime_binding?.freshness || "unknown")}</strong>
          {" · "}
          Primary: <strong>{String(application.activation_composition?.primary_app_artifact_ref?.artifact_slug || "—")}</strong>
          {" · "}
          Policy: <strong>{String(application.activation_composition?.policy_artifact_ref?.artifact_slug || "none")}</strong>
        </p>
      </section>

      <div className="solution-detail-grid">
        <div className="solution-detail-main">
          <section className="card solution-card-compact">
            <h4>New Change Session</h4>
            <p className="muted">Describe the solution-level change request.</p>
            <form className="stack" onSubmit={(event) => void handleCreateSession(event)}>
              <label className="field">
                <span className="field-label">Title (optional)</span>
                <input aria-label="Title" type="text" value={changeTitle} onChange={(event) => setChangeTitle(event.target.value)} placeholder="Campaign monitoring enhancement" />
              </label>
              <label className="field">
                <span className="field-label">Requested change</span>
                <textarea
                  aria-label="Requested change"
                  rows={3}
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

          <section className="card solution-card-compact">
            <h4>Change Sessions</h4>
            {sessions.length ? (
              <div className="table-wrap solution-compact-table-wrap">
                <table className="solution-compact-table">
                  <thead>
                    <tr>
                      <th>Session</th>
                      <th>Status</th>
                      <th>Updated</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((session) => (
                      <tr key={session.id}>
                        <td className="solution-list-name-cell" title={session.title || ""}>{session.title}</td>
                        <td>{session.status}</td>
                        <td className="solution-list-updated-cell">{session.updated_at ? new Date(session.updated_at).toLocaleString() : "—"}</td>
                        <td>
                          <div className="inline-action-row">
                            <button
                              className={`ghost sm ${activeSessionId === session.id ? "active" : ""}`}
                              type="button"
                              onClick={() => {
                                setActiveSessionId(session.id);
                                setSelectedArtifactIds(session.selected_artifact_ids || []);
                                setSelectedWorkstreams(session.confirmed_workstreams || []);
                              }}
                            >
                              {activeSessionId === session.id ? "Selected" : "Select"}
                            </button>
                            <button
                              className="ghost sm"
                              type="button"
                              onClick={() => void handleDeleteSession(session)}
                              disabled={deletingSessionId === session.id}
                              aria-label={`Delete ${session.title}`}
                            >
                              {deletingSessionId === session.id ? "Deleting…" : "Delete"}
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted solution-empty-state">No change sessions yet.</p>
            )}
          </section>

          {activeSession ? (
            <section className="card stack solution-card-compact">
              <h4>Selected Session</h4>
              <p className="muted">
                <strong>{activeSession.title}</strong> · {activeSession.status}
              </p>

              <div className="solution-stage-strip" role="list" aria-label="Session workflow stages">
                {stageRows.map((row) => (
                  <div
                    key={row.key}
                    role="listitem"
                    className={[
                      "solution-stage-pill",
                      row.complete ? "is-complete" : "",
                      currentStageRow?.key === row.key ? "is-current" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {row.label}
                  </div>
                ))}
              </div>

              <div className="solution-next-step-callout">
                <div className="field-label">Workflow guidance</div>
                <p className="solution-empty-state">{nextStepCopy}</p>
              </div>

              <div className="solution-actions-block">
                <div className="inline-action-row">
                  {nextStep === "analyze" ? (
                    <button className="button sm" type="button" onClick={() => void handleGeneratePlan()} disabled={planningSession}>
                      {planningSession ? "Analyzing…" : "Analyze Impacted Artifacts"}
                    </button>
                  ) : nextStep === "save" ? (
                    impactedRows.length ? (
                      <button className="button sm" type="button" onClick={() => void handleSaveImpactedArtifacts()} disabled={saving}>
                        {saving ? "Saving…" : "Save Impacted Artifacts"}
                      </button>
                    ) : (
                      <p className="solution-empty-state">Select suggested workstreams below and confirm focus to continue.</p>
                    )
                  ) : nextStep === "plan" ? (
                    <button className="button sm" type="button" onClick={() => void handleGeneratePlan()} disabled={planningSession}>
                      {planningSession ? "Planning…" : "Generate Cross-Artifact Plan"}
                    </button>
                  ) : nextStep === "approve" ? (
                    <button
                      className="button sm"
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
                      Open Session in Composer
                    </button>
                  ) : nextStep === "stage" ? (
                    <button className="button sm" type="button" onClick={() => void handleStageApply()} disabled={stagingSession || !canStageApply}>
                      {stagingSession ? "Staging…" : "Stage Coordinated Apply"}
                    </button>
                  ) : nextStep === "preview" ? (
                    <button className="button sm" type="button" onClick={() => void handlePreparePreview()} disabled={preparingPreview || !canPreparePreview}>
                      {preparingPreview ? "Preparing…" : "Prepare Preview Handoff"}
                    </button>
                  ) : nextStep === "validate" ? (
                    <button className="button sm" type="button" onClick={() => void handleValidateSession()} disabled={validatingSession || !canValidateSession}>
                      {validatingSession ? "Validating…" : "Run Validation"}
                    </button>
                  ) : null}
                </div>
                <div className="inline-action-row">
                  {impactedRows.length ? (
                    <button className="ghost sm" type="button" onClick={() => void handleSaveImpactedArtifacts()} disabled={saving || !hasImpactedAnalysis}>
                      {saving ? "Saving…" : "Save Impacted Artifacts"}
                    </button>
                  ) : null}
                  <button className="ghost sm" type="button" onClick={() => void handleGeneratePlan()} disabled={planningSession}>
                    {planningSession ? "Planning…" : "Generate Cross-Artifact Plan"}
                  </button>
                  <button
                    className="ghost sm"
                    type="button"
                    onClick={() => void handleStageApply()}
                    disabled={stagingSession || !canStageApply}
                    title={stagingSession || canStageApply ? "" : stageBlockedReason}
                  >
                    {stagingSession ? "Staging…" : "Stage Coordinated Apply"}
                  </button>
                  <button
                    className="ghost sm"
                    type="button"
                    onClick={() => void handlePreparePreview()}
                    disabled={preparingPreview || !canPreparePreview}
                    title={preparingPreview || canPreparePreview ? "" : previewBlockedReason}
                  >
                    {preparingPreview ? "Preparing…" : "Prepare Preview Handoff"}
                  </button>
                  <button
                    className="ghost sm"
                    type="button"
                    onClick={() => void handleValidateSession()}
                    disabled={validatingSession || !canValidateSession}
                    title={validatingSession || canValidateSession ? "" : validateBlockedReason}
                  >
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
              </div>

              <div className="field-label">{impactedRows.length ? "Impacted Artifact Selection" : "Suggested Focus Areas"}</div>
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
              ) : suggestedWorkstreams.length ? (
                <div className="solution-next-step-callout">
                  <p className="solution-empty-state">
                    Analysis completed. No confident artifact IDs were resolved yet. Select and confirm suggested focus areas to continue:
                  </p>
                  <div className="stack">
                    {suggestedWorkstreams.map((item) => {
                      const token = String(item || "").trim().toLowerCase();
                      const checked = selectedWorkstreams.includes(token);
                      return (
                        <label key={token} className="row" style={{ alignItems: "center", gap: 8 }}>
                          <input type="checkbox" checked={checked} onChange={(event) => toggleWorkstreamSelection(token, event.target.checked)} />
                          <span>{workstreamLabel(token)}</span>
                        </label>
                      );
                    })}
                  </div>
                  {confirmedWorkstreams.length ? (
                    <p className="solution-empty-state">
                      Confirmed workstream focus: {confirmedWorkstreams.map((item) => workstreamLabel(item)).join(", ")}
                    </p>
                  ) : null}
                  <div className="inline-action-row">
                    <button className="button sm" type="button" onClick={() => void handleConfirmSuggestedFocus()} disabled={saving || !selectedWorkstreams.length}>
                      {saving ? "Saving…" : "Use Selected Workstreams"}
                    </button>
                  </div>
                </div>
              ) : analysisHasNoConfidentMatches ? (
                <div className="solution-next-step-callout">
                  <p className="solution-empty-state">
                    Analysis completed, but no confident artifact matches were found for this request yet.
                    Continue by generating a targeted plan or refining the request with more specific scope.
                  </p>
                </div>
              ) : (
                <div className="solution-next-step-callout">
                  <p className="solution-empty-state">
                    Impacted artifact analysis is not available yet. This is expected for a new or un-analyzed session.
                    Run <strong>Analyze Impacted Artifacts</strong> to generate suggested artifact focus for this change request.
                  </p>
                </div>
              )}

              {hasPlan ? (
                <section className="stack">
                  <h5>Plan Summary</h5>
                  <div className="solution-plan-summary-grid">
                    <div>
                      <span className="field-label">Title</span>
                      <div className="field-value">{String(activePlan.title || activeSession.title || "—")}</div>
                    </div>
                    <div>
                      <span className="field-label">Requested change</span>
                      <div className="field-value">{planRequestText || "—"}</div>
                    </div>
                  </div>
                  {planImplementationSteps.length ? (
                    <div className="stack">
                      <div className="field-label">Implementation steps</div>
                      <ul className="solution-summary-list">
                        {planImplementationSteps.map((step, index) => (
                          <li key={`impl-${index}`}>{step}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {planValidationSteps.length ? (
                    <div className="stack">
                      <div className="field-label">Validation steps</div>
                      <ul className="solution-summary-list">
                        {planValidationSteps.map((step, index) => (
                          <li key={`val-${index}`}>{step}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {planSharedContracts.length ? (
                    <div className="stack">
                      <div className="field-label">Shared contracts / assumptions</div>
                      <ul className="solution-summary-list">
                        {planSharedContracts.map((item, index) => (
                          <li key={`shared-${index}`}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  <details>
                    <summary>Raw plan (technical details)</summary>
                    <pre className="code-block">{JSON.stringify(activePlan, null, 2)}</pre>
                  </details>
                </section>
              ) : null}

          {stagedArtifacts.length ? (
            <>
              <h5>Staged Multi-Artifact Apply State</h5>
              <div className="table-wrap solution-compact-table-wrap">
                <table className="solution-compact-table">
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
            <p className="muted solution-empty-state">No staged artifacts yet.</p>
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
                  <div className="table-wrap solution-compact-table-wrap">
                    <table className="solution-compact-table">
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
              <div className="table-wrap solution-compact-table-wrap">
                <table className="solution-compact-table">
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
        </div>

        <aside className="solution-detail-secondary">
          <section className="card solution-card-compact">
            <h4>Artifact Membership</h4>
            <p className="muted">Assigned artifacts and their solution roles.</p>
            {memberships.length ? (
              <div className="table-wrap solution-compact-table-wrap">
                <table className="solution-compact-table">
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
                        <td className="solution-list-name-cell" title={item.artifact?.title || item.artifact_id}>
                          {item.artifact?.title || item.artifact_id}
                        </td>
                        <td>{item.role}</td>
                        <td className="solution-list-name-cell" title={item.responsibility_summary || "—"}>{item.responsibility_summary || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted solution-empty-state">No artifacts assigned yet.</p>
            )}
          </section>

          <section className="card solution-card-compact">
            <h4>Add Artifact Membership</h4>
            <p className="muted">Assign coordinated artifacts under this solution.</p>
            <form className="stack solution-membership-form" onSubmit={(event) => void handleAddMembership(event)}>
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
        </aside>
      </div>
    </div>
  );
}
