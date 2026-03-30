import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Layout, Model, Actions, type IJsonModel, type TabNode } from "flexlayout-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import WorkbenchPanelHost, { type ConsolePanelKey, type ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import { useXynConsole } from "../state/xynConsoleStore";
import { useContextualCapabilities } from "../components/console/contextualCapabilities";
import { resolveCapabilityGraphContext } from "../navigation/capabilityContext";
import { executeCapabilityAction } from "../navigation/executeCapabilityAction";
import { emitCapabilityEvent } from "../events/emitCapabilityEvent";
import type { ContextualCapability } from "../../api/types";
import { buildWorkspaceLayout, derivePanelGroupAssignments, readWorkspaceLayout, syncFlexLayoutModel, writeWorkspaceLayout } from "../workspace/workspaceLayout";

export function shouldReuseExistingLayoutOnWorkspaceSwitch(input: {
  previousWorkspaceId: string;
  nextWorkspaceId: string;
  panelCount: number;
}): boolean {
  const previous = String(input.previousWorkspaceId || "").trim();
  const next = String(input.nextWorkspaceId || "").trim();
  if (!previous || !next || previous === next) return false;
  return input.panelCount > 0;
}

export default function WorkbenchPage({
  workspaceName = "",
  workspaceColor = "#6c7a89",
  currentUser = null,
}: {
  workspaceName?: string;
  workspaceColor?: string;
  currentUser?: Record<string, unknown> | null;
}) {
  const {
    setContext,
    setOpen,
    setInputText,
    clearSessionResolution,
    activePanel,
    closePanel,
    openPanel,
    setActivePanelId,
    setCanvasContext,
    setLastArtifactHint,
    panels,
    restorePanels,
    syncPanelGroups,
  } =
    useXynConsole();
  const params = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const showLandingShell = !activePanel;
  const landingContext = useMemo(
    () =>
      resolveCapabilityGraphContext({
        pathname: location.pathname,
        search: location.search,
        explicitContext: "landing",
      }),
    [location.pathname, location.search],
  );
  const { capabilities: landingCapabilities } = useContextualCapabilities({
    enabled: showLandingShell,
    context: showLandingShell ? landingContext : undefined,
    workspaceId: showLandingShell ? workspaceId : undefined,
    includeUnavailable: true,
  });
  const [layoutJson, setLayoutJson] = useState<IJsonModel | null>(null);
  const previousWorkspaceIdRef = useRef<string>("");

  const panelById = useMemo(() => new Map(panels.map((entry) => [entry.panel_id, entry] as const)), [panels]);

  // Stabilize the model: only recreate via Model.fromJson when the set of panel
  // IDs or the layout JSON changes.  Active-tab selection is applied in-place via
  // model.doAction so that flexlayout does NOT remount tab components (which
  // would destroy local state like the settings-hub section selector and
  // multi-select values).
  const panelIdSignature = useMemo(() => panels.map((p) => p.panel_id).join("|"), [panels]);
  const modelRef = useRef<Model | null>(null);
  // Guard: when true, the next onModelChange is from a programmatic doAction
  // and should NOT feed back into setLayoutJson (which would recreate the model).
  const suppressModelChangeRef = useRef(false);

  const model = useMemo(() => {
    const json = syncFlexLayoutModel(layoutJson, panels, activePanel?.panel_id || null);
    const m = Model.fromJson(json);
    modelRef.current = m;
    return m;
    // eslint-disable-next-line react-hooks/exhaustive-deps -- panels is
    // intentionally excluded; panelIdSignature captures structural changes
    // without triggering on param/title updates.
  }, [layoutJson, panelIdSignature]);

  // When only the active panel changes, update the selection in-place so the
  // model reference stays stable and tabs are NOT remounted.
  useEffect(() => {
    if (!modelRef.current || !activePanel?.panel_id) return;
    try {
      suppressModelChangeRef.current = true;
      modelRef.current.doAction(Actions.selectTab(activePanel.panel_id));
    } catch {
      // Tab may not exist yet — will be handled on next structural sync.
    } finally {
      suppressModelChangeRef.current = false;
    }
  }, [activePanel?.panel_id]);

  useEffect(() => {
    setContext({ artifact_id: null, artifact_type: null });
    clearSessionResolution();
    setOpen(true);
  }, [clearSessionResolution, setContext, setOpen]);

  useEffect(() => {
    const previousWorkspaceId = String(previousWorkspaceIdRef.current || "").trim();
    const nextWorkspaceId = String(workspaceId || "").trim();
    const preserveLayout = shouldReuseExistingLayoutOnWorkspaceSwitch({
      previousWorkspaceId,
      nextWorkspaceId,
      panelCount: panels.length,
    });
    previousWorkspaceIdRef.current = nextWorkspaceId;
    if (!nextWorkspaceId) return;
    if (preserveLayout) return;
    const stored = readWorkspaceLayout(nextWorkspaceId);
    if (stored?.panel_ids?.length) {
      setLayoutJson(stored.flexlayout_model as IJsonModel);
    } else {
      setLayoutJson(buildWorkspaceLayout(nextWorkspaceId, panels, activePanel?.panel_id || null).flexlayout_model as IJsonModel);
    }
  }, [workspaceId, panels.length, activePanel?.panel_id]);

  useEffect(() => {
    if (!activePanel) setCanvasContext(null);
  }, [activePanel, setCanvasContext]);

  useEffect(() => {
    if (!workspaceId) return;
    void emitCapabilityEvent({
      eventType: "workspace_initialized",
      workspaceId,
    });
  }, [workspaceId]);

  useEffect(() => {
    if (!workspaceId) return;
    writeWorkspaceLayout(buildWorkspaceLayout(workspaceId, panels, activePanel?.panel_id || null));
  }, [workspaceId, panels, activePanel?.panel_id, layoutJson]);

  useEffect(() => {
    const panelKey = String(searchParams.get("panel") || "").trim().toLowerCase();
    if (!panelKey) return;
    // Deep-link bridge into panel state only.
    // New capability UX should be expressed as panel intents/palette commands,
    // with route-level wrappers kept as compatibility redirects.
    if (panelKey === "platform_settings") {
      if (!activePanel || activePanel.key !== "platform_settings") {
        openPanel({
          key: "platform_settings",
          params: {},
          open_in: "current_panel",
        });
      }
    } else if (panelKey === "solution_list") {
      const nextParams: Record<string, unknown> = {};
      const solutionName = String(searchParams.get("solution_name") || "").trim();
      if (solutionName) nextParams.solution_name = solutionName;
      const createObjective = String(searchParams.get("create_solution_objective") || "").trim();
      const createName = String(searchParams.get("create_solution_name") || "").trim();
      if (createObjective) nextParams.create_solution_objective = createObjective;
      if (createName) nextParams.create_solution_name = createName;
      const shouldOpenWithParams =
        Boolean(solutionName || createObjective || createName)
        && activePanel?.key === "solution_list";
      if (!activePanel || activePanel.key !== "solution_list" || shouldOpenWithParams) {
        openPanel({
          key: "solution_list",
          params: nextParams,
          open_in: "current_panel",
        });
      }
      const next = new URLSearchParams(searchParams);
      next.delete("solution_name");
      next.delete("create_solution_objective");
      next.delete("create_solution_name");
      next.delete("panel");
      setSearchParams(next, { replace: true });
      return;
    } else if (panelKey === "solution_detail") {
      const applicationId = String(searchParams.get("application_id") || "").trim();
      if (!applicationId) return;
      const nextParams: Record<string, unknown> = { application_id: applicationId };
      if (!activePanel || activePanel.key !== "solution_detail" || String(activePanel.params?.application_id || "") !== applicationId) {
        openPanel({
          key: "solution_detail",
          params: nextParams,
          open_in: "current_panel",
        });
      }
      const next = new URLSearchParams(searchParams);
      next.delete("application_id");
      next.delete("panel");
      setSearchParams(next, { replace: true });
      return;
    } else if (panelKey === "campaign_list") {
      const create = ["1", "true", "yes"].includes(String(searchParams.get("create") || "").trim().toLowerCase());
      const nextParams: Record<string, unknown> = {};
      if (create) nextParams.create = true;
      const activeCreate = Boolean(activePanel?.params?.create === true);
      if (!activePanel || activePanel.key !== "campaign_list" || activeCreate !== create) {
        openPanel({
          key: "campaign_list",
          params: nextParams,
          open_in: "current_panel",
        });
      }
      const next = new URLSearchParams(searchParams);
      next.delete("create");
      next.delete("panel");
      setSearchParams(next, { replace: true });
      return;
    } else if (panelKey === "composer_detail" || panelKey === "composer") {
      const nextParams: Record<string, unknown> = {};
      const applicationId = String(searchParams.get("application_id") || "").trim();
      const applicationPlanId = String(searchParams.get("application_plan_id") || "").trim();
      const goalId = String(searchParams.get("goal_id") || "").trim();
      const threadId = String(searchParams.get("thread_id") || "").trim();
      const factoryKey = String(searchParams.get("factory_key") || "").trim();
      const solutionChangeSessionId = String(searchParams.get("solution_change_session_id") || "").trim();
      if (applicationId) nextParams.application_id = applicationId;
      if (applicationPlanId) nextParams.application_plan_id = applicationPlanId;
      if (goalId) nextParams.goal_id = goalId;
      if (threadId) nextParams.thread_id = threadId;
      if (factoryKey) nextParams.factory_key = factoryKey;
      if (solutionChangeSessionId) nextParams.solution_change_session_id = solutionChangeSessionId;
      if (!activePanel || activePanel.key !== "composer_detail") {
        openPanel({
          key: "composer_detail",
          params: nextParams,
          open_in: "current_panel",
        });
      }
      const next = new URLSearchParams(searchParams);
      next.delete("application_id");
      next.delete("application_plan_id");
      next.delete("goal_id");
      next.delete("thread_id");
      next.delete("factory_key");
      next.delete("solution_change_session_id");
      next.delete("panel");
      setSearchParams(next, { replace: true });
      return;
    } else {
      return;
    }
    const next = new URLSearchParams(searchParams);
    next.delete("panel");
    setSearchParams(next, { replace: true });
  }, [activePanel, openPanel, searchParams, setSearchParams]);

  useEffect(() => {
    const revise = String(searchParams.get("revise") || "").trim().toLowerCase();
    if (revise !== "1") return;
    const prompt = String(searchParams.get("prompt") || "").trim();
    const artifactSlug = String(searchParams.get("artifact_slug") || "").trim();
    const artifactTitle = String(searchParams.get("artifact_title") || "").trim() || artifactSlug;
    const artifactType = String(searchParams.get("artifact_type") || "").trim() || "Artifact";
    setContext({ artifact_id: null, artifact_type: null });
    if (artifactSlug) {
      setLastArtifactHint({
        artifact_id: artifactSlug,
        artifact_type: artifactType,
        artifact_state: "installed",
        title: artifactTitle,
        route: `/w/${encodeURIComponent(workspaceId)}/workbench`,
      });
    }
    setInputText(prompt || "Add ");
    setOpen(true);
    const next = new URLSearchParams(searchParams);
    next.delete("revise");
    next.delete("prompt");
    next.delete("artifact_slug");
    next.delete("artifact_title");
    next.delete("artifact_type");
    setSearchParams(next, { replace: true });
  }, [searchParams, setContext, setInputText, setLastArtifactHint, setOpen, setSearchParams, workspaceId]);

  const availableLandingCapabilities = useMemo(
    () => landingCapabilities.filter((entry) => entry.available !== false),
    [landingCapabilities]
  );
  const unavailableLandingCapabilities = useMemo(
    () => landingCapabilities.filter((entry) => entry.available === false).slice(0, 3),
    [landingCapabilities]
  );

  const suggestions = (
    landingCapabilities.length
      ? availableLandingCapabilities.slice(0, 6).map((entry) => ({
          id: entry.id,
          label: entry.name,
          description: entry.description,
          prompt: String(entry.prompt_template || "").trim() || entry.name,
          capability: entry,
        }))
      : [
          {
            id: "build_application",
            label: "Build an application",
            description: "Create a new software application.",
            prompt: "Build an application that...",
            capability: {
              id: "build_application",
              name: "Build an application",
              description: "Create a new software application.",
              prompt_template: "Build an application that...",
              visibility: "primary",
              action_type: "prompt",
            } satisfies ContextualCapability,
          },
          {
            id: "write_article",
            label: "Write an article",
            description: "Create a written article artifact.",
            prompt: "Write an article about...",
            capability: {
              id: "write_article",
              name: "Write an article",
              description: "Create a written article artifact.",
              prompt_template: "Write an article about...",
              visibility: "primary",
              action_type: "prompt",
            } satisfies ContextualCapability,
          },
          {
            id: "create_explainer_video",
            label: "Create an explainer video",
            description: "Create a narrated explainer video artifact.",
            prompt: "Create an explainer video explaining...",
            capability: {
              id: "create_explainer_video",
              name: "Create an explainer video",
              description: "Create a narrated explainer video artifact.",
              prompt_template: "Create an explainer video explaining...",
              visibility: "primary",
              action_type: "prompt",
            } satisfies ContextualCapability,
          },
          {
            id: "explore_artifacts",
            label: "Explore artifacts",
            description: "View existing artifacts in the workspace.",
            prompt: "Show my artifacts",
            capability: {
              id: "explore_artifacts",
              name: "Explore artifacts",
              description: "View existing artifacts in the workspace.",
              prompt_template: "Show my artifacts",
              visibility: "secondary",
              action_type: "prompt",
            } satisfies ContextualCapability,
          },
        ]
  ).slice(0, 6);
  const handleSuggestion = (capability: ContextualCapability, prompt: string) => {
    executeCapabilityAction({
      capability,
      navigate,
      workspaceId,
      insertPrompt: (text) => {
        setInputText(text || prompt);
        setOpen(true);
      },
    });
  };

  const factory = useCallback((node: TabNode) => {
    const panelId = String(node.getId() || "");
    const panelState = panelById.get(panelId);
    if (!panelState) {
      return (
        <section className="card">
          <p className="muted">Panel unavailable.</p>
        </section>
      );
    }
    const panel: ConsolePanelSpec = {
      panel_id: panelState.panel_id,
      panel_type: panelState.panel_type,
      instance_key: panelState.instance_key,
      title: panelState.title,
      key: panelState.key as ConsolePanelKey,
      params: panelState.params || {},
      active_group_id: panelState.active_group_id,
      open_in: "current_panel",
    };
    return (
      <WorkbenchPanelHost
        panel={panel}
        workspaceId={workspaceId}
        workspaceName={workspaceName}
        workspaceColor={workspaceColor}
        currentUser={currentUser}
        onOpenPanel={(next) =>
          openPanel({
            key: next.key,
            params: next.params || {},
            open_in: next.open_in || "new_panel",
            return_to_panel_id: next.return_to_panel_id,
            title: next.title,
          })
        }
        onContextChange={(context) => {
          setCanvasContext((context || null) as never);
        }}
        onClosePanel={() => {
          if (panel.panel_id) closePanel(panel.panel_id);
        }}
      />
    );
  }, [panelById, workspaceId, workspaceName, workspaceColor, openPanel, setCanvasContext, closePanel]);

  const handleModelChange = (nextModel: Model) => {
    // Skip feedback when the change came from our own programmatic doAction
    // (e.g. selecting the active tab).  Feeding it back would recreate the
    // model and potentially remount tab components.
    if (suppressModelChangeRef.current) return;
    const nextJson = nextModel.toJson();
    setLayoutJson(nextJson);
    syncPanelGroups(derivePanelGroupAssignments(nextJson as IJsonModel));
    writeWorkspaceLayout({
      workspace_id: workspaceId,
      flexlayout_model: nextJson,
      panel_ids: panels.map((entry) => entry.panel_id),
      last_updated: new Date().toISOString(),
    });
  };

  return (
    <div className="workbench-page">
      {!activePanel ? (
        <div className="workbench-start-shell">
          <section className="card workbench-start-card">
            <p className="muted">Press ⌘K / Ctrl+K or use Xyn to issue a command.</p>
            {suggestions.length ? (
              <div className="workbench-suggestion-grid">
                {suggestions.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    className="ghost workbench-suggestion-chip"
                    onClick={() => handleSuggestion(entry.capability, entry.prompt)}
                  >
                    <strong>{entry.label}</strong>
                    <span className="muted small">{entry.description}</span>
                  </button>
                ))}
              </div>
            ) : null}
            {unavailableLandingCapabilities.length ? (
              <div className="workbench-unavailable-capabilities">
                <h3>Unavailable Right Now</h3>
                <div className="workbench-unavailable-list">
                  {unavailableLandingCapabilities.map((entry) => (
                    <div key={entry.id} className="workbench-unavailable-item" aria-disabled="true">
                      <strong>{entry.name}</strong>
                      {entry.failure_message ? <span className="muted small">{entry.failure_message}</span> : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {panels.length ? (
        <section className="workbench-canvas">
          <Layout
            model={model}
            factory={factory}
            onModelChange={handleModelChange}
            onAction={(action) => {
              if (action.type === Actions.deleteTab("").type) {
                const panelId = String(action.data?.node || "");
                if (panelId) closePanel(panelId);
              }
              if (action.type === Actions.selectTab("").type) {
                const panelId = String(action.data?.tabNode || "");
                if (panelId) setActivePanelId(panelId);
              }
              return action;
            }}
          />
        </section>
      ) : null}
    </div>
  );
}
