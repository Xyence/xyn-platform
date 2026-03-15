import { useCallback, useEffect, useMemo, useState } from "react";
import { Layout, Model, Actions, type IJsonModel, type TabNode } from "flexlayout-react";
import { useParams, useSearchParams } from "react-router-dom";
import WorkbenchPanelHost, { type ConsolePanelKey, type ConsolePanelSpec } from "../components/console/WorkbenchPanelHost";
import { useCapabilitySuggestions } from "../components/console/capabilitySuggestions";
import { useXynConsole } from "../state/xynConsoleStore";
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
    requestSubmit,
    setLastArtifactHint,
    panels,
    restorePanels,
    syncPanelGroups,
  } =
    useXynConsole();
  const params = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const workspaceId = String(params.workspaceId || "").trim();
  const { landingSuggestions } = useCapabilitySuggestions(workspaceId);
  const [layoutJson, setLayoutJson] = useState<IJsonModel | null>(null);

  const panelById = useMemo(() => new Map(panels.map((entry) => [entry.panel_id, entry] as const)), [panels]);
  const model = useMemo(() => Model.fromJson(syncFlexLayoutModel(layoutJson, panels, activePanel?.panel_id || null)), [layoutJson, panels, activePanel?.panel_id]);

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
    landingSuggestions.length
      ? landingSuggestions.slice(0, 6).map((entry) => entry.prompt)
      : [
          "List artifacts",
          "Show runs",
          "Open platform settings",
          "Provision Xyn instance (remote)",
        ]
  ).slice(0, 6);

  const handleSuggestion = (prompt: string) => {
    setInputText(prompt);
    setOpen(true);
    requestSubmit();
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
    <>
      {!activePanel ? (
        <div className="workbench-start-shell">
          <section className="card workbench-start-card">
            <p className="muted">Press ⌘K / Ctrl+K or use Xyn to issue a command.</p>
            {suggestions.length ? (
              <div className="workbench-suggestion-grid">
                {suggestions.map((entry) => (
                  <button key={entry} type="button" className="ghost workbench-suggestion-chip" onClick={() => handleSuggestion(entry)}>
                    {entry}
                  </button>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      <section className="workbench-canvas">
        {panels.length ? (
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
        ) : null}
      </section>
    </>
  );
}
