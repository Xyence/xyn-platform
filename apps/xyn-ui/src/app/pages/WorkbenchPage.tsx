import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Layout, Model, Actions, type IJsonModel, type TabNode } from "flexlayout-react";
import { useParams, useSearchParams } from "react-router-dom";
import WorkbenchPanelHost, { type ConsolePanelKey, type ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import { useXynConsole } from "../state/xynConsoleStore";
import { useContextualCapabilities } from "../components/console/contextualCapabilities";
import { buildWorkspaceLayout, derivePanelGroupAssignments, readWorkspaceLayout, syncFlexLayoutModel, writeWorkspaceLayout } from "../workspace/workspaceLayout";

export default function WorkbenchPage({
  workspaceName = "",
  workspaceColor = "#6c7a89",
}: {
  workspaceName?: string;
  workspaceColor?: string;
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
  const [searchParams, setSearchParams] = useSearchParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const { capabilities: landingCapabilities } = useContextualCapabilities({ context: "landing" });
  const [layoutJson, setLayoutJson] = useState<IJsonModel | null>(null);

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
    const stored = readWorkspaceLayout(workspaceId);
    if (stored?.panel_ids?.length) {
      setLayoutJson(stored.flexlayout_model as IJsonModel);
    } else {
      setLayoutJson(buildWorkspaceLayout(workspaceId, panels, activePanel?.panel_id || null).flexlayout_model as IJsonModel);
    }
  }, [workspaceId]);

  useEffect(() => {
    if (!activePanel) setCanvasContext(null);
  }, [activePanel, setCanvasContext]);

  useEffect(() => {
    if (!workspaceId) return;
    writeWorkspaceLayout(buildWorkspaceLayout(workspaceId, panels, activePanel?.panel_id || null));
  }, [workspaceId, panels, activePanel?.panel_id, layoutJson]);

  useEffect(() => {
    const panelKey = String(searchParams.get("panel") || "").trim().toLowerCase();
    if (panelKey !== "platform_settings") return;
    if (!activePanel || activePanel.key !== "platform_settings") {
      openPanel({
        key: "platform_settings",
        params: {},
        open_in: "current_panel",
      });
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
    setContext({ artifact_id: null, artifact_type: null });
    if (artifactSlug) {
      setLastArtifactHint({
        artifact_id: artifactSlug,
        artifact_type: "GeneratedApplication",
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
    setSearchParams(next, { replace: true });
  }, [searchParams, setContext, setInputText, setLastArtifactHint, setOpen, setSearchParams, workspaceId]);

  const suggestions = (
    landingCapabilities.length
      ? landingCapabilities.slice(0, 6).map((entry) => ({
          id: entry.id,
          label: entry.name,
          description: entry.description,
          prompt: String(entry.prompt_template || "").trim() || entry.name,
        }))
      : [
          { id: "build_application", label: "Build an application", description: "Create a new software application.", prompt: "Build an application that..." },
          { id: "write_article", label: "Write an article", description: "Create a written article artifact.", prompt: "Write an article about..." },
          { id: "create_explainer_video", label: "Create an explainer video", description: "Create a narrated explainer video artifact.", prompt: "Create an explainer video explaining..." },
          { id: "explore_artifacts", label: "Explore artifacts", description: "View existing artifacts in the workspace.", prompt: "Show my artifacts" },
        ]
  ).slice(0, 6);

  const handleSuggestion = (prompt: string) => {
    setInputText(prompt);
    setOpen(true);
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
                  <button key={entry.id} type="button" className="ghost workbench-suggestion-chip" onClick={() => handleSuggestion(entry.prompt)}>
                    <strong>{entry.label}</strong>
                    <span className="muted small">{entry.description}</span>
                  </button>
                ))}
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
