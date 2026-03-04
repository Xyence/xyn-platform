import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import InlineMessage from "../../components/InlineMessage";
import {
  canonizeDraftArtifactToBlueprint,
  createDraftSessionArtifact,
  deleteDraftSession,
  enqueueDraftGeneration,
  enqueueDraftRevision,
  extractDraftSessionReleaseTarget,
  listEnvironments,
  enqueueVoiceNoteTranscription,
  getContextPackDefaults,
  getDraftSession,
  listContextPacks,
  listDraftSessionRevisions,
  listDraftSessionVoiceNotes,
  listDraftSessions,
  resolveDraftSessionContext,
  saveDraftSession,
  snapshotDraftSession,
  submitDraftSession,
  updateDraftSession,
  uploadVoiceNote,
} from "../../api/xyn";
import { listInstances } from "../../api/client";
import type {
  BlueprintDraftSession,
  BlueprintDraftSessionDetail,
  BlueprintVoiceNote,
  ContextPackSummary,
  DraftSessionRevision,
  EnvironmentSummary,
  ProvisionedInstance,
} from "../../api/types";
import Popover from "../components/ui/Popover";
import { Menu, MenuItem } from "../components/ui/Menu";
import { useNotifications } from "../state/notificationsStore";
import { notifyFailed, notifyQueued, notifySucceeded } from "../../lib/notifyFromJob";

const NEW_DRAFT_DEFAULT_TITLE = "Untitled draft";

export default function DraftSessionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { draftId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const selectedFetchSeq = useRef(0);
  const selectedSessionIdRef = useRef<string | null>(null);

  const [sessions, setSessions] = useState<BlueprintDraftSession[]>([]);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [contextPacks, setContextPacks] = useState<ContextPackSummary[]>([]);
  const [voiceNotes, setVoiceNotes] = useState<BlueprintVoiceNote[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<BlueprintDraftSessionDetail | null>(null);
  const [sessionRevisions, setSessionRevisions] = useState<DraftSessionRevision[]>([]);
  const [revisionSearch, setRevisionSearch] = useState("");
  const [revisionPage, setRevisionPage] = useState(1);
  const [revisionTotal, setRevisionTotal] = useState(0);
  const [draftJsonText, setDraftJsonText] = useState("");
  const [revisionInstruction, setRevisionInstruction] = useState("");
  const [sessionContextPackIds, setSessionContextPackIds] = useState<string[]>([]);
  const [recommendedSessionPackIds, setRecommendedSessionPackIds] = useState<string[]>([]);
  const [requiredPackNames, setRequiredPackNames] = useState<string[]>([]);
  const [contextPackPurposeFilter, setContextPackPurposeFilter] = useState<"all" | "planner" | "coder">("all");
  const [contextPackScopeFilter, setContextPackScopeFilter] = useState<"all" | "global" | "namespace" | "project">(
    "all"
  );

  const [filterQ, setFilterQ] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>(searchParams.get("status") || "");
  const [filterKind, setFilterKind] = useState<"" | "blueprint" | "solution">(
    (searchParams.get("kind") as "blueprint" | "solution" | "") || ""
  );
  const [filterNamespace, setFilterNamespace] = useState(searchParams.get("namespace") || "");
  const [filterProjectKey, setFilterProjectKey] = useState(searchParams.get("project_key") || "");

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newSessionTitle, setNewSessionTitle] = useState(NEW_DRAFT_DEFAULT_TITLE);
  const [newSessionKind, setNewSessionKind] = useState<"blueprint" | "solution">("blueprint");
  const [newSessionNamespace, setNewSessionNamespace] = useState("");
  const [newSessionProjectKey, setNewSessionProjectKey] = useState("");
  const [newSessionGenerateCode, setNewSessionGenerateCode] = useState(false);
  const [newSessionPrompt, setNewSessionPrompt] = useState("");
  const [newSessionTranscript, setNewSessionTranscript] = useState("");
  const [selectedCreateContextPackIds, setSelectedCreateContextPackIds] = useState<string[]>([]);
  const [didManuallyEditCreatePacks, setDidManuallyEditCreatePacks] = useState(false);

  const [showSubmitModal, setShowSubmitModal] = useState(false);
  const [submitNamespace, setSubmitNamespace] = useState("");
  const [submitBlueprintName, setSubmitBlueprintName] = useState("");
  const [submitEnvironmentId, setSubmitEnvironmentId] = useState("");
  const [submitInstanceId, setSubmitInstanceId] = useState("");
  const [submitHostname, setSubmitHostname] = useState("");
  const [submitTlsMode, setSubmitTlsMode] = useState<"none" | "nginx+acme" | "host-ingress">("host-ingress");
  const [submitRemoteRoot, setSubmitRemoteRoot] = useState("");
  const [environments, setEnvironments] = useState<EnvironmentSummary[]>([]);
  const [instances, setInstances] = useState<ProvisionedInstance[]>([]);
  const [showWorkflowMenu, setShowWorkflowMenu] = useState(false);
  const [generationStepMessage, setGenerationStepMessage] = useState<string | null>(null);

  const [loading, setLoading] = useState(false);
  const [creatingSession, setCreatingSession] = useState(false);
  const [canonizing, setCanonizing] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { push } = useNotifications();
  const previousSelectedStatusRef = useRef<string | null>(null);

  const revisionPageSize = 5;
  const revisionTotalPages = Math.max(1, Math.ceil(revisionTotal / revisionPageSize));

  const filteredContextPacks = useMemo(
    () =>
      contextPacks.filter((pack) => {
        if (contextPackPurposeFilter !== "all" && pack.purpose !== contextPackPurposeFilter) return false;
        if (contextPackScopeFilter !== "all" && pack.scope !== contextPackScopeFilter) return false;
        return true;
      }),
    [contextPackPurposeFilter, contextPackScopeFilter, contextPacks]
  );

  const selectedSessionVoiceTranscript = useMemo(
    () => (selectedSession?.source_artifacts ?? []).find((item) => item.type === "audio_transcript")?.content ?? "",
    [selectedSession]
  );

  const hasPromptInputs = useMemo(() => {
    if (!selectedSession) return false;
    const hasInitialPrompt = Boolean((selectedSession.initial_prompt ?? "").trim());
    const hasSourceText = Boolean(
      (selectedSession.source_artifacts ?? []).some((artifact) => (artifact.content ?? "").trim().length > 0)
    );
    return hasInitialPrompt || hasSourceText;
  }, [selectedSession]);

  const hasDraftOutput = useMemo(
    () => Boolean(selectedSession?.has_generated_output || selectedSession?.draft),
    [selectedSession]
  );

  const hasFatalValidationErrors = useMemo(
    () => Boolean((selectedSession?.validation_errors ?? []).length > 0),
    [selectedSession]
  );

  const submitInstances = useMemo(() => {
    if (!submitEnvironmentId) return instances;
    return instances.filter((instance) => (instance.environment_id || "") === submitEnvironmentId);
  }, [instances, submitEnvironmentId]);

  const refreshSessions = useCallback(async () => {
    const payload = await listDraftSessions({
      status: filterStatus || undefined,
      kind: filterKind || undefined,
      namespace: filterNamespace || undefined,
      project_key: filterProjectKey || undefined,
      q: filterQ.trim() || undefined,
    });
    setSessions(payload.sessions);
    setSessionsLoaded(true);
    const params = new URLSearchParams();
    if (filterStatus) params.set("status", filterStatus);
    if (filterKind) params.set("kind", filterKind);
    if (filterNamespace) params.set("namespace", filterNamespace);
    if (filterProjectKey) params.set("project_key", filterProjectKey);
    const next = params.toString();
    const current = searchParams.toString();
    if (next !== current) {
      setSearchParams(params, { replace: true });
    }
  }, [filterKind, filterNamespace, filterProjectKey, filterQ, filterStatus, searchParams, setSearchParams]);

  const refreshSelectedSession = useCallback(async (sessionId: string) => {
    const detail = await getDraftSession(sessionId);
    if (selectedSessionIdRef.current !== sessionId) return;
    setSelectedSession(detail);
    setDraftJsonText(detail.draft ? JSON.stringify(detail.draft, null, 2) : "");
    setRevisionInstruction(detail.revision_instruction ?? "");
    const ids = detail.selected_context_pack_ids ?? detail.context_pack_ids ?? [];
    setSessionContextPackIds(ids);
    const defaults = await getContextPackDefaults({
      draft_kind: detail.kind === "solution" ? "solution" : "blueprint",
      namespace: detail.namespace ?? undefined,
      project_key: detail.project_key ?? undefined,
      generate_code: detail.kind === "solution",
    });
    setRecommendedSessionPackIds(defaults.recommended_context_pack_ids);
    setRequiredPackNames(defaults.required_pack_names);
    const notes = await listDraftSessionVoiceNotes(sessionId);
    if (selectedSessionIdRef.current !== sessionId) return;
    setVoiceNotes(notes.voice_notes);
  }, []);

  const refreshSessionRevisions = useCallback(async () => {
    if (!selectedSessionId) return;
    const payload = await listDraftSessionRevisions(selectedSessionId, {
      q: revisionSearch.trim() || undefined,
      page: revisionPage,
      page_size: revisionPageSize,
    });
    setSessionRevisions(payload.revisions);
    setRevisionTotal(payload.total);
  }, [revisionPage, revisionSearch, selectedSessionId]);

  const refreshRecommendedCreateContextPacks = useCallback(
    async (options?: {
      kind?: "blueprint" | "solution";
      namespace?: string;
      projectKey?: string;
      generateCode?: boolean;
      promptOnReset?: boolean;
    }) => {
      const kind = options?.kind ?? newSessionKind;
      const namespace = options?.namespace ?? newSessionNamespace;
      const projectKey = options?.projectKey ?? newSessionProjectKey;
      const generateCode = options?.generateCode ?? newSessionGenerateCode;
      const defaults = await getContextPackDefaults({
        draft_kind: kind,
        namespace: namespace || undefined,
        project_key: projectKey || undefined,
        generate_code: generateCode,
      });
      if (!didManuallyEditCreatePacks) {
        setSelectedCreateContextPackIds(defaults.recommended_context_pack_ids);
        return;
      }
      if (
        options?.promptOnReset &&
        defaults.recommended_context_pack_ids.join(",") !== selectedCreateContextPackIds.join(",") &&
        confirm("Reset context packs to recommended defaults?")
      ) {
        setSelectedCreateContextPackIds(defaults.recommended_context_pack_ids);
        setDidManuallyEditCreatePacks(false);
      }
    },
    [
      didManuallyEditCreatePacks,
      newSessionGenerateCode,
      newSessionKind,
      newSessionNamespace,
      newSessionProjectKey,
      selectedCreateContextPackIds,
    ]
  );

  useEffect(() => {
    (async () => {
      try {
        setError(null);
        const packs = await listContextPacks({ active: true });
        setContextPacks(packs.context_packs);
        const envData = await listEnvironments();
        setEnvironments(envData.environments ?? []);
        const instanceData = await listInstances();
        setInstances(instanceData.instances ?? []);
      } catch (err) {
        setError((err as Error).message);
      }
    })();
  }, []);

  useEffect(() => {
    refreshSessions().catch((err) => setError((err as Error).message));
  }, [refreshSessions]);

  useEffect(() => {
    const onDraftCreated = () => {
      refreshSessions().catch((err) => setError((err as Error).message));
    };
    window.addEventListener("xyn:draft-session-created", onDraftCreated as EventListener);
    return () => {
      window.removeEventListener("xyn:draft-session-created", onDraftCreated as EventListener);
    };
  }, [refreshSessions]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshSessions().catch((err) => setError((err as Error).message));
    }, 5000);
    return () => {
      window.clearInterval(timer);
    };
  }, [refreshSessions]);

  useEffect(() => {
    if (showCreateModal && contextPacks.length > 0) {
      refreshRecommendedCreateContextPacks().catch((err) => setError((err as Error).message));
    }
  }, [contextPacks.length, refreshRecommendedCreateContextPacks, showCreateModal]);

  useEffect(() => {
    if (draftId) {
      if (!sessionsLoaded) return;
      const exists = sessions.some((item) => item.id === draftId);
      if (exists) {
        const selectedExists = !!selectedSessionId && sessions.some((item) => item.id === selectedSessionId);
        // Preserve an explicit in-UI selection while route navigation catches up.
        if (!selectedExists || selectedSessionId === draftId) {
          setSelectedSessionId(draftId);
        }
      } else {
        const fallbackId = sessions[0]?.id ?? null;
        setSelectedSessionId(fallbackId);
        const search = searchParams.toString();
        navigate(
          fallbackId ? `/app/drafts/${fallbackId}${search ? `?${search}` : ""}` : `/app/drafts${search ? `?${search}` : ""}`,
          { replace: true }
        );
      }
      return;
    }
    if (sessions.length === 0) {
      setSelectedSessionId(null);
      setSelectedSession(null);
      return;
    }
    if (!selectedSessionId || !sessions.some((item) => item.id === selectedSessionId)) {
      setSelectedSessionId(sessions[0].id);
    }
  }, [draftId, navigate, searchParams, selectedSessionId, sessions, sessionsLoaded]);

  useEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
    setShowWorkflowMenu(false);
  }, [selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId) return;
    const requestId = ++selectedFetchSeq.current;
    refreshSelectedSession(selectedSessionId).catch((err) => {
      if (selectedFetchSeq.current === requestId) {
        const message = (err as Error).message || "";
        if (message.includes("(404)") || message.toLowerCase().includes("not found")) {
          setSelectedSession(null);
          setDraftJsonText("");
          setRevisionInstruction("");
          setSessionContextPackIds([]);
          setVoiceNotes([]);
          setError(null);
          refreshSessions().catch((refreshErr) => setError((refreshErr as Error).message));
          return;
        }
        setError(message);
      }
    });
  }, [refreshSelectedSession, refreshSessions, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId || !selectedSession) return;
    if (!["queued", "drafting"].includes(selectedSession.status)) return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      if (cancelled) return;
      try {
        await refreshSelectedSession(selectedSessionId);
        await refreshSessionRevisions();
      } catch (err) {
        if (!cancelled) {
          setError((err as Error).message);
        }
      }
    }, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshSelectedSession, refreshSessionRevisions, selectedSession, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId || !selectedSession) {
      previousSelectedStatusRef.current = null;
      return;
    }
    const previous = previousSelectedStatusRef.current;
    const current = selectedSession.status;
    if (previous && previous !== current) {
      if (
        ["queued", "drafting", "running"].includes(previous) &&
        ["ready", "published", "submitted", "ready_with_errors"].includes(current)
      ) {
        notifySucceeded(push, {
          action: "draft.status",
          entityType: "draft_session",
          entityId: selectedSessionId,
          title: "Draft processing finished",
          message: current,
          href: `/app/drafts/${selectedSessionId}`,
          dedupeKey: `draft.status:${selectedSessionId}`,
        });
      } else if (["queued", "drafting", "running"].includes(previous) && current === "failed") {
        notifyFailed(push, {
          action: "draft.status",
          entityType: "draft_session",
          entityId: selectedSessionId,
          title: "Draft processing failed",
          message:
            ((selectedSession as unknown as Record<string, unknown>).error_message as string | undefined) ||
            "See draft validation/output details.",
          href: `/app/drafts/${selectedSessionId}`,
          dedupeKey: `draft.status:${selectedSessionId}`,
        });
      }
    }
    previousSelectedStatusRef.current = current;
  }, [push, selectedSession, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId) return;
    if (draftId === selectedSessionId) return;
    const search = searchParams.toString();
    navigate(
      {
        pathname: `/app/drafts/${selectedSessionId}`,
        search: search ? `?${search}` : "",
      },
      { replace: true }
    );
  }, [draftId, navigate, searchParams, selectedSessionId]);

  useEffect(() => {
    const search = searchParams.toString();
    const expectedPath = selectedSessionId ? `/app/drafts/${selectedSessionId}` : "/app/drafts";
    const expectedUrl = `${expectedPath}${search ? `?${search}` : ""}`;
    const actualUrl = `${location.pathname}${location.search}`;
    if (actualUrl === expectedUrl) return;
    if (!selectedSessionId && draftId) {
      navigate(`/app/drafts${search ? `?${search}` : ""}`, { replace: true });
    }
  }, [draftId, location.pathname, location.search, navigate, searchParams, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId) return;
    refreshSessionRevisions().catch((err) => setError((err as Error).message));
  }, [refreshSessionRevisions, selectedSessionId]);

  useEffect(() => {
    if (revisionPage > revisionTotalPages) setRevisionPage(revisionTotalPages);
  }, [revisionPage, revisionTotalPages]);

  const openCreate = () => {
    setShowCreateModal(true);
    setNewSessionTitle(NEW_DRAFT_DEFAULT_TITLE);
    setNewSessionKind("blueprint");
    setNewSessionNamespace(filterNamespace || "core");
    setNewSessionProjectKey(filterProjectKey || "");
    setNewSessionGenerateCode(false);
    setNewSessionPrompt("");
    setNewSessionTranscript("");
    setDidManuallyEditCreatePacks(false);
    setSelectedCreateContextPackIds([]);
  };

  const handleCreateSession = async () => {
    try {
      setCreatingSession(true);
      setError(null);
      const created = await createDraftSessionArtifact({
        title: newSessionTitle.trim() || NEW_DRAFT_DEFAULT_TITLE,
        kind: newSessionKind,
        namespace: newSessionNamespace.trim() || undefined,
        project_key: newSessionProjectKey.trim() || undefined,
        initial_prompt: newSessionPrompt.trim(),
        selected_context_pack_ids:
          selectedCreateContextPackIds.length > 0 ? selectedCreateContextPackIds : undefined,
      });
      const sessionId = created.session_id;
      if (newSessionTranscript.trim()) {
        await updateDraftSession(sessionId, {
          source_artifacts: [{ type: "audio_transcript", content: newSessionTranscript.trim() }],
        });
      }
      await refreshSessions();
      setSelectedSessionId(sessionId);
      navigate(`/app/drafts/${sessionId}`);
      setShowCreateModal(false);
      push({
        level: "success",
        title: "Draft session created",
        message: sessionId,
        entityType: "draft_session",
        entityId: sessionId,
        status: "succeeded",
        action: "draft.create",
        href: `/app/drafts/${sessionId}`,
        dedupeKey: `draft.create:${sessionId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setCreatingSession(false);
    }
  };

  const handleCanonizeToBlueprint = async () => {
    if (!selectedSession?.artifact_id) {
      setError("Draft artifact is missing. Save/reload the draft and try again.");
      return;
    }
    try {
      setCanonizing(true);
      setError(null);
      const result = await canonizeDraftArtifactToBlueprint(selectedSession.artifact_id, {
        title: selectedSession.title || selectedSession.id,
        namespace: selectedSession.namespace || undefined,
        description: selectedSession.requirements_summary || undefined,
      });
      notifySucceeded(push, {
        action: "draft.canonize",
        entityType: "draft_session",
        entityId: selectedSession.id,
        title: "Canonized as Blueprint",
        message: result.blueprint_id,
        href: `/app/blueprints/${result.blueprint_id}`,
        dedupeKey: `draft.canonize:${selectedSession.id}`,
      });
      navigate(`/app/blueprints/${result.blueprint_id}`);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.canonize",
        entityType: "draft_session",
        entityId: selectedSession.id,
        title: "Canonization failed",
        message,
        href: `/app/drafts/${selectedSession.id}`,
        dedupeKey: `draft.canonize:${selectedSession.id}`,
      });
    } finally {
      setCanonizing(false);
    }
  };

  const handleUpdateSessionMetadata = async () => {
    if (!selectedSessionId || !selectedSession) return;
    try {
      setLoading(true);
      setError(null);
      await updateDraftSession(selectedSessionId, {
        title: selectedSession.title || selectedSession.id,
        kind: (selectedSession.kind as "blueprint" | "solution") || "blueprint",
        namespace: selectedSession.namespace || undefined,
        project_key: selectedSession.project_key || undefined,
        initial_prompt: selectedSession.initial_prompt || "",
        revision_instruction: revisionInstruction || selectedSession.revision_instruction || "",
        selected_context_pack_ids: sessionContextPackIds,
        source_artifacts: selectedSession.source_artifacts,
      });
      await refreshSelectedSession(selectedSessionId);
      push({
        level: "success",
        title: "Draft session metadata saved",
        entityType: "draft_session",
        entityId: selectedSessionId,
        action: "draft.update",
        dedupeKey: `draft.update:${selectedSessionId}`,
      });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.release_target.extract",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Deployment target extraction failed",
        message,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.release_target.extract:${selectedSessionId}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteSession = async () => {
    if (!selectedSessionId) return;
    if (!confirm("Delete this draft session?")) return;
    try {
      setLoading(true);
      setError(null);
      await deleteDraftSession(selectedSessionId);
      await refreshSessions();
      setSelectedSessionId(null);
      navigate("/app/drafts", { replace: true });
      push({
        level: "success",
        title: "Draft session deleted",
        entityType: "draft_session",
        entityId: selectedSessionId,
        action: "draft.delete",
        dedupeKey: `draft.delete:${selectedSessionId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshContext = async () => {
    if (!selectedSessionId) return;
    if (
      selectedSession?.effective_context_hash &&
      !confirm("Refresh context now? This will replace the cached context preview/hash.")
    ) {
      return;
    }
    try {
      setLoading(true);
      setError(null);
      await resolveDraftSessionContext(selectedSessionId, { context_pack_ids: sessionContextPackIds });
      await refreshSelectedSession(selectedSessionId);
      push({
        level: "success",
        title: "Context refreshed",
        entityType: "draft_session",
        entityId: selectedSessionId,
        action: "draft.context.refresh",
        dedupeKey: `draft.context.refresh:${selectedSessionId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleReExtractReleaseTarget = async () => {
    if (!selectedSessionId) return;
    try {
      setLoading(true);
      setError(null);
      const result = await extractDraftSessionReleaseTarget(selectedSessionId, {});
      await refreshSelectedSession(selectedSessionId);
      const warnings = result.warnings && result.warnings.length > 0 ? ` Warnings: ${result.warnings.join("; ")}` : "";
      push({
        level: result.warnings?.length ? "warning" : "success",
        title: "Deployment target extracted",
        message: warnings.trim() || undefined,
        entityType: "draft_session",
        entityId: selectedSessionId,
        action: "draft.release_target.extract",
        dedupeKey: `draft.release_target.extract:${selectedSessionId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateDraft = async () => {
    if (!selectedSessionId || !selectedSession) return;
    if (!hasPromptInputs) {
      setError("Provide an initial prompt or prompt source before generating.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      setGenerationStepMessage("Refreshing context...");
      await updateDraftSession(selectedSessionId, {
        title: selectedSession.title || selectedSession.id,
        kind: (selectedSession.kind as "blueprint" | "solution") || "blueprint",
        namespace: selectedSession.namespace || undefined,
        project_key: selectedSession.project_key || undefined,
        initial_prompt: selectedSession.initial_prompt || "",
        selected_context_pack_ids: sessionContextPackIds,
        source_artifacts: selectedSession.source_artifacts,
      });
      setGenerationStepMessage("Generating draft...");
      await enqueueDraftGeneration(selectedSessionId);
      notifyQueued(push, {
        action: "draft.generate",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Draft generation queued",
        message: selectedSession.title || selectedSession.id,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.generate:${selectedSessionId}`,
      });
      setSelectedSession((prev) =>
        prev
          ? {
              ...prev,
              status: "drafting",
              initial_prompt_locked:
                Boolean((prev.initial_prompt || "").trim()) || Boolean(prev.initial_prompt_locked),
            }
          : prev
      );
      await refreshSelectedSession(selectedSessionId);
      await refreshSessionRevisions();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.generate",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Draft generation failed to queue",
        message,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.generate:${selectedSessionId}`,
      });
    } finally {
      setGenerationStepMessage(null);
      setLoading(false);
    }
  };

  const handleReviseDraft = async () => {
    if (!selectedSessionId) return;
    if (!selectedSession?.has_generated_output) {
      setError("Revision instruction is only available after initial output is generated.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      await enqueueDraftRevision(selectedSessionId, { instruction: revisionInstruction });
      notifyQueued(push, {
        action: "draft.revise",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Draft revision queued",
        message: selectedSession?.title || selectedSessionId,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.revise:${selectedSessionId}`,
      });
      setRevisionInstruction("");
      await refreshSelectedSession(selectedSessionId);
      await refreshSessionRevisions();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.revise",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Draft revision failed to queue",
        message,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.revise:${selectedSessionId}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSaveDraft = async () => {
    if (!selectedSessionId) return;
    try {
      setLoading(true);
      setError(null);
      const parsed = draftJsonText.trim().length > 0 ? JSON.parse(draftJsonText) : {};
      await saveDraftSession(selectedSessionId, { draft_json: parsed });
      await refreshSelectedSession(selectedSessionId);
      await refreshSessionRevisions();
      notifySucceeded(push, {
        action: "draft.save",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Draft JSON saved",
        dedupeKey: `draft.save:${selectedSessionId}`,
      });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.submit",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Submit as Blueprint failed",
        message,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.submit:${selectedSessionId}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const handleSaveSnapshot = async () => {
    if (!selectedSessionId) return;
    if (!hasDraftOutput) {
      setError("Generate or save a draft output before creating a snapshot.");
      return;
    }
    try {
      setLoading(true);
      setError(null);
      await snapshotDraftSession(selectedSessionId, { note: "manual snapshot" });
      await refreshSelectedSession(selectedSessionId);
      await refreshSessionRevisions();
      notifySucceeded(push, {
        action: "draft.snapshot",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Snapshot saved",
        dedupeKey: `draft.snapshot:${selectedSessionId}`,
      });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      notifyFailed(push, {
        action: "draft.voice.transcribe",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Recording upload failed",
        message,
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.voice.transcribe:${selectedSessionId}`,
      });
    } finally {
      setLoading(false);
    }
  };

  const openSubmitModal = () => {
    const existingProjectKey = selectedSession?.project_key || "";
    const [ns, ...rest] = existingProjectKey.split(".");
    setSubmitNamespace(selectedSession?.namespace || ns || "core");
    setSubmitBlueprintName(rest.join(".") || selectedSession?.title?.toLowerCase().replace(/\s+/g, "-") || "");
    const resolved = selectedSession?.extracted_release_target_resolution;
    setSubmitEnvironmentId(resolved?.environment_id || "");
    setSubmitInstanceId(resolved?.instance_id || "");
    setSubmitHostname(resolved?.fqdn || "");
    setSubmitTlsMode(
      (selectedSession?.extracted_release_target_intent?.tls_mode as "none" | "nginx+acme" | "host-ingress" | undefined) ||
        "host-ingress"
    );
    const runtime = selectedSession?.extracted_release_target_intent?.runtime;
    setSubmitRemoteRoot((runtime && typeof runtime === "object" ? String((runtime as Record<string, unknown>).remote_root || "") : "") || "");
    setShowSubmitModal(true);
  };

  const handleSubmitSession = async () => {
    if (!selectedSessionId || !selectedSession) return;
    const initialPrompt = (selectedSession.initial_prompt || "").trim();
    if (!initialPrompt) {
      setError("Initial prompt is required before submission.");
      return;
    }
    const nextProjectKey = `${submitNamespace.trim()}.${submitBlueprintName.trim()}`.replace(/^\./, "");
    if (!submitNamespace.trim() || !submitBlueprintName.trim()) {
      setError("Blueprint namespace and name are required.");
      return;
    }
    if (!submitEnvironmentId || !submitInstanceId || !submitHostname.trim()) {
      setError("Release target confirmation is required: environment, instance, and hostname.");
      return;
    }
    const packNamesById = new Map(contextPacks.map((pack) => [pack.id, pack.name]));
    const selectedNames = new Set((sessionContextPackIds || []).map((id) => packNamesById.get(id)).filter(Boolean));
    const missingRequired = requiredPackNames.filter((name) => !selectedNames.has(name));
    if (missingRequired.length > 0) {
      setError(`Missing required context packs: ${missingRequired.join(", ")}`);
      return;
    }
    try {
      setLoading(true);
      setError(null);
      await updateDraftSession(selectedSessionId, {
        title: selectedSession.title || selectedSession.id,
        kind: (selectedSession.kind as "blueprint" | "solution") || "blueprint",
        namespace: submitNamespace.trim(),
        project_key: nextProjectKey,
        initial_prompt: selectedSession.initial_prompt || "",
        selected_context_pack_ids: sessionContextPackIds,
        source_artifacts: selectedSession.source_artifacts,
      });
      const result = await submitDraftSession(selectedSessionId, {
        initial_prompt: initialPrompt,
        selected_context_pack_ids: sessionContextPackIds,
        source_artifacts: selectedSession.source_artifacts,
        generate_code: selectedSession.kind === "solution",
        release_target: {
          environment_id: submitEnvironmentId,
          target_instance_id: submitInstanceId,
          fqdn: submitHostname.trim(),
          hostname: submitHostname.trim(),
          environment_name: environments.find((env) => env.id === submitEnvironmentId)?.name,
          target_instance_name: instances.find((instance) => instance.id === submitInstanceId)?.name,
        },
      });
      setShowSubmitModal(false);
      await refreshSelectedSession(selectedSessionId);
      await refreshSessionRevisions();
      notifySucceeded(push, {
        action: "draft.submit",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: selectedSession.kind === "solution" ? "Submitted as Solution" : "Submitted as Blueprint",
        message: result.status,
        href: result.entity_type === "blueprint" ? "/app/blueprints" : undefined,
        dedupeKey: `draft.submit:${selectedSessionId}`,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleVoiceUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    if (!event.target.files || event.target.files.length === 0 || !selectedSessionId) return;
    try {
      setUploading(true);
      setError(null);
      const file = event.target.files[0];
      const uploaded = await uploadVoiceNote(file, { session_id: selectedSessionId, language_code: "en-US" });
      await enqueueVoiceNoteTranscription(uploaded.voice_note_id);
      notifyQueued(push, {
        action: "draft.voice.transcribe",
        entityType: "draft_session",
        entityId: selectedSessionId,
        title: "Recording uploaded",
        message: "Transcription queued",
        href: `/app/drafts/${selectedSessionId}`,
        dedupeKey: `draft.voice.transcribe:${selectedSessionId}:${uploaded.voice_note_id}`,
      });
      const notes = await listDraftSessionVoiceNotes(selectedSessionId);
      setVoiceNotes(notes.voice_notes);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  };

  const addTranscriptToPromptSources = (text: string) => {
    if (!selectedSession || !text.trim()) return;
    setSelectedSession((prev) => {
      if (!prev) return prev;
      const existing = (prev.source_artifacts ?? []).filter((item) => item.type !== "audio_transcript");
      const current = (prev.source_artifacts ?? []).find((item) => item.type === "audio_transcript")?.content ?? "";
      const merged = current.includes(text) ? current : [current.trim(), text.trim()].filter(Boolean).join("\n\n");
      return { ...prev, source_artifacts: [...existing, { type: "audio_transcript", content: merged }] };
    });
  };

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Draft Sessions</h2>
          <p className="muted">Create and iterate blueprint/solution drafts independently from blueprint browsing.</p>
        </div>
        <div className="inline-actions">
          {selectedSession?.artifact_id && (
            <button className="primary" onClick={handleCanonizeToBlueprint} disabled={loading || canonizing}>
              {canonizing ? "Canonizing..." : "Canonize → Create Blueprint"}
            </button>
          )}
          <button className="ghost" onClick={() => refreshSessions()} disabled={loading}>
            Refresh
          </button>
          <button className="primary" data-tour="draft-create" data-testid="draft-create" onClick={openCreate}>
            New draft session
          </button>
        </div>
      </div>

      {error && <InlineMessage tone="error" title="Request failed" body={error} />}

      <div className="layout">
        <section className="card">
          <div className="card-header">
            <h3>Draft sessions</h3>
          </div>
          <div className="form-grid">
            <label>
              Search
              <input value={filterQ} onChange={(event) => setFilterQ(event.target.value)} placeholder="Filter drafts..." />
            </label>
            <label>
              Status
              <select value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}>
                <option value="">All</option>
                <option value="drafting">drafting</option>
                <option value="queued">queued</option>
                <option value="ready">ready</option>
                <option value="ready_with_errors">ready_with_errors</option>
                <option value="published">published</option>
                <option value="archived">archived</option>
                <option value="failed">failed</option>
              </select>
            </label>
            <label>
              Kind
              <select value={filterKind} onChange={(event) => setFilterKind(event.target.value as "" | "blueprint" | "solution")}>
                <option value="">All</option>
                <option value="blueprint">blueprint</option>
                <option value="solution">solution</option>
              </select>
            </label>
            <label>
              Namespace
              <input value={filterNamespace} onChange={(event) => setFilterNamespace(event.target.value)} />
            </label>
            <label className="span-full">
              Project key
              <input value={filterProjectKey} onChange={(event) => setFilterProjectKey(event.target.value)} />
            </label>
          </div>
          <div className="form-actions">
            <button className="ghost" onClick={() => refreshSessions()} disabled={loading}>
              Apply filters
            </button>
            <button
              className="ghost"
              onClick={() => {
                setFilterQ("");
                setFilterStatus("");
                setFilterKind("");
                setFilterNamespace("");
                setFilterProjectKey("");
              }}
              disabled={loading}
            >
              Clear
            </button>
          </div>
          <div className="instance-list">
            {sessions.map((session) => (
              <button
                key={session.id}
                className={`instance-row ${selectedSessionId === session.id ? "active" : ""}`}
                onClick={() => {
                  setSelectedSessionId(session.id);
                  const search = searchParams.toString();
                  navigate(
                    {
                      pathname: `/app/drafts/${session.id}`,
                      search: search ? `?${search}` : "",
                    },
                    { replace: true }
                  );
                }}
              >
                <div>
                  <strong>{session.title || session.name}</strong>
                  <span className="muted small">
                    {(session.kind || "blueprint")} {session.project_key ? `• ${session.project_key}` : ""}
                  </span>
                </div>
                <span className="muted small">{session.status}</span>
              </button>
            ))}
            {sessions.length === 0 && <p className="muted">No draft sessions found.</p>}
          </div>
        </section>

        <section className="card">
          {!selectedSession ? (
            <div className="stack">
              <h3>Draft detail</h3>
              <p className="muted">Select a draft session to view details.</p>
              <p className="muted">
                Looking for blueprints? <Link to="/app/blueprints">Go to Blueprints</Link>
              </p>
            </div>
          ) : (
            <div className="draft-session-layout">
              <section className="draft-section">
                <div className="card-header">
                  <h4>Session</h4>
                  <div className="inline-actions">
                    <button className="ghost" onClick={handleUpdateSessionMetadata} disabled={loading}>
                      Save metadata
                    </button>
                    <button className="danger" onClick={handleDeleteSession} disabled={loading}>
                      Delete
                    </button>
                  </div>
                </div>
                <label className="stacked-field">
                  Title
                  <input
                    value={selectedSession.title || ""}
                    onChange={(event) =>
                      setSelectedSession((prev) => (prev ? { ...prev, title: event.target.value } : prev))
                    }
                  />
                </label>
                <div className="form-grid">
                  <label>
                    Draft kind
                    <select
                      value={selectedSession.kind || "blueprint"}
                      onChange={async (event) => {
                        const nextKind = event.target.value as "blueprint" | "solution";
                        setSelectedSession((prev) => (prev ? { ...prev, kind: nextKind } : prev));
                        const defaults = await getContextPackDefaults({
                          draft_kind: nextKind,
                          namespace: selectedSession.namespace ?? undefined,
                          project_key: selectedSession.project_key ?? undefined,
                          generate_code: nextKind === "solution",
                        });
                        setRecommendedSessionPackIds(defaults.recommended_context_pack_ids);
                        setRequiredPackNames(defaults.required_pack_names);
                      }}
                    >
                      <option value="blueprint">Blueprint draft</option>
                      <option value="solution">Solution draft</option>
                    </select>
                  </label>
                  <label>
                    Namespace
                    <input
                      value={selectedSession.namespace ?? ""}
                      onChange={(event) =>
                        setSelectedSession((prev) => (prev ? { ...prev, namespace: event.target.value } : prev))
                      }
                    />
                  </label>
                  <label className="span-full">
                    Project key (optional)
                    <input
                      value={selectedSession.project_key ?? ""}
                      onChange={(event) =>
                        setSelectedSession((prev) => (prev ? { ...prev, project_key: event.target.value } : prev))
                      }
                    />
                  </label>
                </div>
                <div className="detail-grid draft-session-meta">
                  <div>
                    <div className="label">Status</div>
                    <span className="muted">{selectedSession.status}</span>
                  </div>
                  <div>
                    <div className="label">Job ID</div>
                    <span className="muted draft-inline-wrap">{selectedSession.job_id ?? "—"}</span>
                  </div>
                  <div>
                    <div className="label">Context hash</div>
                    <span className="muted draft-inline-wrap">{selectedSession.effective_context_hash ?? "—"}</span>
                  </div>
                  <div>
                    <div className="label">Blueprint kind</div>
                    <span className="muted">{selectedSession.blueprint_kind}</span>
                  </div>
                </div>
                <div className={`draft-context-status ${selectedSession.context_stale ? "stale" : "fresh"}`}>
                  <span className="label">Context</span>
                  <span className="muted">
                    {selectedSession.context_stale
                      ? "stale — will refresh on generate"
                      : "up to date"}
                  </span>
                  <span className="muted small">
                    {selectedSession.effective_context_hash
                      ? `hash: ${selectedSession.effective_context_hash.slice(0, 8)}…`
                      : "hash: —"}
                  </span>
                  <span className="muted small">
                    {selectedSession.context_resolved_at
                      ? `resolved: ${new Date(selectedSession.context_resolved_at).toLocaleString()}`
                      : "resolved: never"}
                  </span>
                </div>
              </section>

              <section className="draft-section">
                <h4>Context packs</h4>
                <div className="inline-actions draft-context-filters">
                  <select
                    value={contextPackPurposeFilter}
                    onChange={(event) => setContextPackPurposeFilter(event.target.value as "all" | "planner" | "coder")}
                  >
                    <option value="all">Purpose: all</option>
                    <option value="planner">Purpose: planner</option>
                    <option value="coder">Purpose: coder</option>
                  </select>
                  <select
                    value={contextPackScopeFilter}
                    onChange={(event) =>
                      setContextPackScopeFilter(event.target.value as "all" | "global" | "namespace" | "project")
                    }
                  >
                    <option value="all">Scope: all</option>
                    <option value="global">Scope: global</option>
                    <option value="namespace">Scope: namespace</option>
                    <option value="project">Scope: project</option>
                  </select>
                </div>
                <label className="stacked-field">
                  Context packs for session
                  <select
                    className="draft-pack-select"
                    multiple
                    size={Math.min(Math.max(filteredContextPacks.length, 3), 8)}
                    value={sessionContextPackIds}
                    onChange={(event) =>
                      setSessionContextPackIds(Array.from(event.target.selectedOptions).map((opt) => opt.value))
                    }
                  >
                    {filteredContextPacks.map((pack) => (
                      <option key={pack.id} value={pack.id}>
                        {pack.name} ({pack.scope}) v{pack.version} [{pack.purpose}]
                        {pack.namespace ? ` ns:${pack.namespace}` : ""}
                        {pack.project_key ? ` project:${pack.project_key}` : ""}
                      </option>
                    ))}
                  </select>
                </label>
                <span className="muted small">
                  Required defaults: {requiredPackNames.length > 0 ? requiredPackNames.join(", ") : "none"}
                </span>
                <span className="muted small">
                  Recommended defaults:{" "}
                  {recommendedSessionPackIds.length > 0
                    ? recommendedSessionPackIds
                        .map((id) => contextPacks.find((pack) => pack.id === id)?.name ?? id)
                        .join(", ")
                    : "none"}
                </span>
              </section>

              <section className="draft-section">
                <div className="card-header">
                  <h4>Deployment target</h4>
                  <button className="ghost" onClick={handleReExtractReleaseTarget} disabled={loading}>
                    Re-extract
                  </button>
                </div>
                <div className="detail-grid draft-session-meta">
                  <div>
                    <div className="label">Status</div>
                    <span className="muted">
                      {selectedSession.extracted_release_target_intent
                        ? selectedSession.extracted_release_target_intent_source === "model"
                          ? "Extracted with assistance"
                          : "Extracted from prompt"
                        : "Not found"}
                    </span>
                  </div>
                  <div>
                    <div className="label">Environment</div>
                    <span className="muted">{selectedSession.extracted_release_target_resolution?.environment_name ?? "—"}</span>
                  </div>
                  <div>
                    <div className="label">Instance</div>
                    <span className="muted">{selectedSession.extracted_release_target_resolution?.instance_name ?? "—"}</span>
                  </div>
                  <div>
                    <div className="label">Hostname</div>
                    <span className="muted draft-inline-wrap">{selectedSession.extracted_release_target_resolution?.fqdn ?? "—"}</span>
                  </div>
                </div>
                {selectedSession.extracted_release_target_warnings && selectedSession.extracted_release_target_warnings.length > 0 && (
                  <div className="stack">
                    {selectedSession.extracted_release_target_warnings.map((warning, index) => (
                      <span className="muted small" key={`${warning}-${index}`}>
                        Warning: {warning}
                      </span>
                    ))}
                    <span className="muted small">Fix in Submit by selecting explicit release target fields.</span>
                  </div>
                )}
              </section>

              <section className="draft-section">
                <h4>Workflow</h4>
                <div className="inline-actions draft-workflow-actions">
                  <button className="ghost" data-tour="draft-generate" onClick={handleGenerateDraft} disabled={loading || !hasPromptInputs}>
                    Generate draft
                  </button>
                  <button
                    className="ghost"
                    data-tour="draft-promote"
                    data-testid="draft-promote"
                    onClick={openSubmitModal}
                    disabled={loading || !hasDraftOutput || hasFatalValidationErrors}
                  >
                    {selectedSession.kind === "solution" ? "Submit as Solution" : "Submit as Blueprint"}
                  </button>
                  <div className="draft-workflow-overflow">
                    <button
                      className="ghost"
                      onClick={() => setShowWorkflowMenu((prev) => !prev)}
                      aria-expanded={showWorkflowMenu}
                      aria-haspopup="menu"
                    >
                      More
                    </button>
                    <Popover open={showWorkflowMenu} onClose={() => setShowWorkflowMenu(false)} className="draft-workflow-popover">
                      <Menu>
                        <MenuItem
                          onSelect={() => {
                            setShowWorkflowMenu(false);
                            void handleRefreshContext();
                          }}
                        >
                          Refresh context
                        </MenuItem>
                        <MenuItem
                          onSelect={() => {
                            setShowWorkflowMenu(false);
                            void handleSaveSnapshot();
                          }}
                        >
                          Save snapshot
                        </MenuItem>
                        <MenuItem
                          onSelect={() => {
                            setShowWorkflowMenu(false);
                            push({
                              level: "info",
                              title: "Context details",
                              message: `hash=${selectedSession.effective_context_hash || "—"}; resolved_at=${
                                selectedSession.context_resolved_at || "never"
                              }`,
                              entityType: "draft_session",
                              entityId: selectedSession.id,
                              action: "draft.context.view",
                              dedupeKey: `draft.context.view:${selectedSession.id}`,
                            });
                          }}
                        >
                          View context details
                        </MenuItem>
                      </Menu>
                    </Popover>
                  </div>
                </div>
                {generationStepMessage && <span className="muted small">{generationStepMessage}</span>}
                {hasFatalValidationErrors && (
                  <span className="muted small">
                    Submit is disabled while validation errors are present.
                  </span>
                )}
              </section>

              <section className="draft-section">
                <h4>Prompt</h4>
                <label className="stacked-field">
                  Initial prompt
                  <textarea
                    rows={8}
                    value={selectedSession.initial_prompt ?? ""}
                    disabled={Boolean(selectedSession.initial_prompt_locked)}
                    onChange={(event) =>
                      setSelectedSession((prev) => (prev ? { ...prev, initial_prompt: event.target.value } : prev))
                    }
                  />
                </label>
                {selectedSession.initial_prompt_locked && (
                  <span className="muted small">
                    Initial prompt is locked after first generation. Use revision instructions for changes.
                  </span>
                )}
                <label className="stacked-field">
                  Prompt sources: Add transcript text
                  <textarea
                    rows={6}
                    value={selectedSessionVoiceTranscript}
                    onChange={(event) =>
                      setSelectedSession((prev) => {
                        if (!prev) return prev;
                        const others = (prev.source_artifacts ?? []).filter((item) => item.type !== "audio_transcript");
                        const next = event.target.value.trim();
                        return {
                          ...prev,
                          source_artifacts: next ? [...others, { type: "audio_transcript", content: next }] : others,
                        };
                      })
                    }
                  />
                </label>
              </section>

              <section className="draft-section">
                <div className="card-header">
                  <h4>Voice recordings</h4>
                  <button
                    className="ghost"
                    onClick={async () => {
                      if (!selectedSessionId) return;
                      const notes = await listDraftSessionVoiceNotes(selectedSessionId);
                      setVoiceNotes(notes.voice_notes);
                    }}
                    disabled={loading}
                  >
                    Refresh
                  </button>
                </div>
                <label className="file-input">
                  <input type="file" accept="audio/*" onChange={handleVoiceUpload} disabled={uploading || !selectedSessionId} />
                  <span className="button-like">{uploading ? "Uploading..." : "Upload recording"}</span>
                </label>
                {voiceNotes.length === 0 ? (
                  <p className="muted">No recordings yet.</p>
                ) : (
                  voiceNotes.map((note) => (
                    <div key={note.id} className="item-row">
                      <div>
                        <strong>{note.title || "Recording"}</strong>
                        <span className="muted small">{note.status}</span>
                        {note.transcript_text && <span className="muted small">{note.transcript_text}</span>}
                      </div>
                      <div className="inline-actions">
                        {note.transcript_text && (
                          <button className="ghost small" onClick={() => addTranscriptToPromptSources(note.transcript_text || "")}>
                            Add transcript to prompt sources
                          </button>
                        )}
                        <span className="muted small">{note.created_at ?? "—"}</span>
                      </div>
                    </div>
                  ))
                )}
              </section>

              <section className="draft-section">
                <h4>Revision</h4>
                <label className="stacked-field">
                  Revision instruction (for changes after initial draft)
                  <textarea
                    rows={4}
                    value={revisionInstruction || selectedSession.revision_instruction || ""}
                    onChange={(event) => setRevisionInstruction(event.target.value)}
                    disabled={!selectedSession.has_generated_output || !(selectedSession.initial_prompt ?? "").trim()}
                  />
                </label>
                <span className="muted small">Use this only after an initial draft has been generated.</span>
                <button className="ghost" onClick={handleReviseDraft} disabled={loading || !selectedSession.has_generated_output}>
                  Revise draft
                </button>
              </section>

              <section className="draft-section">
                <div className="card-header">
                  <h4>Revisions</h4>
                </div>
                <label className="stacked-field">
                  Search revisions
                  <input
                    value={revisionSearch}
                    placeholder="Search by instruction, summary, or diff..."
                    onChange={(event) => {
                      setRevisionSearch(event.target.value);
                      setRevisionPage(1);
                    }}
                  />
                </label>
                {sessionRevisions.length === 0 ? (
                  <span className="muted">No revisions yet.</span>
                ) : (
                  <div className="instance-list">
                    {sessionRevisions.map((rev) => (
                      <div key={rev.id} className="instance-row">
                        <div>
                          <strong>
                            r{rev.revision_number} • {rev.action}
                          </strong>
                          <span className="muted small">{rev.instruction || rev.diff_summary || "No instruction"}</span>
                        </div>
                        <div className="stack" style={{ alignItems: "flex-end", gap: 4 }}>
                          <span className="muted small">{new Date(rev.created_at).toLocaleString()}</span>
                          <span className="muted small">Errors: {rev.validation_errors_count}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <div className="inline-actions">
                  <button
                    className="ghost small"
                    onClick={() => setRevisionPage((prev) => Math.max(1, prev - 1))}
                    disabled={revisionPage <= 1}
                  >
                    Prev
                  </button>
                  <span className="muted small">
                    Page {revisionPage} / {revisionTotalPages}
                  </span>
                  <button
                    className="ghost small"
                    onClick={() => setRevisionPage((prev) => Math.min(revisionTotalPages, prev + 1))}
                    disabled={revisionPage >= revisionTotalPages}
                  >
                    Next
                  </button>
                </div>
              </section>

              <section className="draft-section">
                <div className="card-header">
                  <h4>Draft output</h4>
                  <button className="ghost" onClick={handleSaveDraft} disabled={loading}>
                    Save draft JSON
                  </button>
                </div>
                <label className="stacked-field">
                  Draft JSON
                  <textarea className="draft-json-editor" rows={16} value={draftJsonText} onChange={(event) => setDraftJsonText(event.target.value)} />
                </label>
                {selectedSession.requirements_summary && (
                  <div className="stack">
                    <strong>Requirements summary</strong>
                    <pre className="draft-output-pre">{selectedSession.requirements_summary}</pre>
                  </div>
                )}
                {selectedSession.diff_summary && (
                  <div className="stack">
                    <strong>Diff summary</strong>
                    <pre className="draft-output-pre">{selectedSession.diff_summary}</pre>
                  </div>
                )}
                <div className="stack">
                  <strong>Validation errors</strong>
                  {(selectedSession.validation_errors ?? []).length === 0 ? (
                    <span className="muted">No validation errors.</span>
                  ) : (
                    (selectedSession.validation_errors ?? []).map((err) => (
                      <span key={err} className="muted">
                        {err}
                      </span>
                    ))
                  )}
                </div>
                <div className="stack">
                  <strong>Effective context preview</strong>
                  <pre className="draft-output-pre">{selectedSession.effective_context_preview ?? "No context preview."}</pre>
                </div>
              </section>
            </div>
          )}
        </section>
      </div>

      {showCreateModal && (
        <div className="modal-backdrop" onClick={() => setShowCreateModal(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>New draft session</h3>
            <div className="form-grid">
              <label className="span-full">
                Title
                <input value={newSessionTitle} onChange={(event) => setNewSessionTitle(event.target.value)} />
              </label>
              <label>
                Draft kind
                <select
                  value={newSessionKind}
                  onChange={async (event) => {
                    const nextKind = event.target.value as "blueprint" | "solution";
                    setNewSessionKind(nextKind);
                    if (nextKind === "blueprint") setNewSessionGenerateCode(false);
                    await refreshRecommendedCreateContextPacks({
                      kind: nextKind,
                      generateCode: nextKind === "solution" ? newSessionGenerateCode : false,
                      promptOnReset: true,
                    });
                  }}
                >
                  <option value="blueprint">Blueprint draft</option>
                  <option value="solution">Solution draft</option>
                </select>
              </label>
              <label>
                Namespace (optional)
                <input
                  value={newSessionNamespace}
                  onChange={async (event) => {
                    const namespace = event.target.value;
                    setNewSessionNamespace(namespace);
                    await refreshRecommendedCreateContextPacks({ namespace, promptOnReset: true });
                  }}
                />
              </label>
              <label className="span-full">
                Project key (optional)
                <input
                  value={newSessionProjectKey}
                  onChange={async (event) => {
                    const projectKey = event.target.value;
                    setNewSessionProjectKey(projectKey);
                    await refreshRecommendedCreateContextPacks({ projectKey, promptOnReset: true });
                  }}
                />
              </label>
              <label className="span-full checkbox">
                <input
                  type="checkbox"
                  checked={newSessionGenerateCode}
                  disabled={newSessionKind === "blueprint"}
                  onChange={async (event) => {
                    const checked = event.target.checked;
                    setNewSessionGenerateCode(checked);
                    await refreshRecommendedCreateContextPacks({ generateCode: checked, promptOnReset: true });
                  }}
                />
                Generate implementation/code
              </label>
              <label className="span-full">
                Initial prompt
                <textarea rows={5} value={newSessionPrompt} onChange={(event) => setNewSessionPrompt(event.target.value)} />
              </label>
              <label className="span-full">
                Add transcript text (optional)
                <textarea rows={4} value={newSessionTranscript} onChange={(event) => setNewSessionTranscript(event.target.value)} />
              </label>
              <label className="span-full">
                Context packs
                <select
                  multiple
                  size={Math.min(Math.max(filteredContextPacks.length, 3), 8)}
                  value={selectedCreateContextPackIds}
                  onChange={(event) => {
                    setDidManuallyEditCreatePacks(true);
                    setSelectedCreateContextPackIds(Array.from(event.target.selectedOptions).map((opt) => opt.value));
                  }}
                >
                  {filteredContextPacks.map((pack) => (
                    <option key={pack.id} value={pack.id}>
                      {pack.name} ({pack.scope}) v{pack.version} [{pack.purpose}]
                      {pack.namespace ? ` ns:${pack.namespace}` : ""}
                      {pack.project_key ? ` project:${pack.project_key}` : ""}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="form-actions" style={{ marginTop: 12 }}>
              <button className="primary" onClick={handleCreateSession} disabled={creatingSession}>
                {creatingSession ? "Creating..." : "Create draft session"}
              </button>
              <button className="ghost" onClick={() => setShowCreateModal(false)} disabled={creatingSession}>
                Cancel
              </button>
            </div>
          </section>
        </div>
      )}

      {showSubmitModal && (
        <div className="modal-backdrop" onClick={() => setShowSubmitModal(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Submit as Blueprint</h3>
            <p className="muted">Confirm the blueprint destination and release target before submission.</p>
            <div className="form-grid">
              <label>
                Blueprint namespace
                <input value={submitNamespace} onChange={(event) => setSubmitNamespace(event.target.value)} />
              </label>
              <label>
                Blueprint name
                <input value={submitBlueprintName} onChange={(event) => setSubmitBlueprintName(event.target.value)} />
              </label>
              <label className="span-full">
                Project key
                <input value={`${submitNamespace}.${submitBlueprintName}`.replace(/^\./, "")} readOnly />
              </label>
              <label>
                Environment
                <select
                  value={submitEnvironmentId}
                  onChange={(event) => {
                    setSubmitEnvironmentId(event.target.value);
                    setSubmitInstanceId("");
                  }}
                >
                  <option value="">Select environment</option>
                  {environments.map((env) => (
                    <option key={env.id} value={env.id}>
                      {env.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Instance
                <select value={submitInstanceId} onChange={(event) => setSubmitInstanceId(event.target.value)}>
                  <option value="">Select instance</option>
                  {submitInstances.map((instance) => (
                    <option key={instance.id} value={instance.id}>
                      {instance.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                TLS mode
                <select
                  value={submitTlsMode}
                  onChange={(event) => setSubmitTlsMode(event.target.value as "none" | "nginx+acme" | "host-ingress")}
                >
                  <option value="host-ingress">host-ingress (Traefik)</option>
                  <option value="none">none</option>
                  <option value="nginx+acme">nginx+acme</option>
                </select>
              </label>
              <label>
                Remote root (optional)
                <input value={submitRemoteRoot} onChange={(event) => setSubmitRemoteRoot(event.target.value)} />
              </label>
              <label className="span-full">
                Hostname (FQDN)
                <input value={submitHostname} onChange={(event) => setSubmitHostname(event.target.value)} />
              </label>
              {selectedSession?.extracted_release_target_warnings && selectedSession.extracted_release_target_warnings.length > 0 && (
                <div className="span-full stack">
                  {selectedSession.extracted_release_target_warnings.map((warning, index) => (
                    <span className="muted small" key={`submit-warning-${index}`}>
                      Warning: {warning}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="form-actions" style={{ marginTop: 12 }}>
              <button className="primary" onClick={handleSubmitSession} disabled={loading}>
                Confirm submit
              </button>
              <button className="ghost" onClick={() => setShowSubmitModal(false)} disabled={loading}>
                Cancel
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
