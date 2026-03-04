import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams } from "react-router-dom";
import { ChevronDown, ChevronUp, History, Lock, MessageSquareMore, Pencil, Plus, SlidersHorizontal, Sparkles, Trash2 } from "lucide-react";
import { renderMarkdown } from "../../public/markdown";
import {
  commentOnWorkspaceArtifact,
  moderateWorkspaceComment,
  reactToWorkspaceArtifact,
  listAiAgents,
  listArticleCategories,
  invokeAi,
  convertArticleHtmlToMarkdown,
  createArticleRevision,
  generateArticleVideoStoryboard,
  getArticleVideoAiConfig,
  getArtifact,
  getArticle,
  getArtifactRawArtifactJson,
  getArtifactRawFileDownloadUrl,
  getArtifactRawFilePreview,
  getArtifactRawMetadata,
  getMe,
  listArtifactRuntimeRoles,
  listArtifactRawFiles,
  listArtifactSurfaces,
  getPlatformConfig,
  initializeArticleVideo,
  listArticleRevisions,
  listArticleVideoRenders,
  listContextPacks,
  renderArticleVideo,
  retryVideoRender,
  cancelVideoRender,
  transitionArticle,
  updateArticleVideoAiConfig,
  updateArticle,
} from "../../api/xyn";
import type {
  AiAgent,
  ArticleDetail,
  ArticleFormat,
  ArticleRevision,
  ArtifactRuntimeRole,
  ArtifactSurface,
  ContextPackSummary,
  ArtifactRawMetadataResponse,
  RawFileEntry,
  VideoAiConfigEntry,
  VideoRender,
  VideoSpec,
} from "../../api/types";
import MarkdownWysiwygEditor, { type EditorSelectionPayload } from "../components/editor/MarkdownWysiwygEditor";
import ContextRefinementTool from "../components/editor/ContextRefinementTool";
import CompactPaneTabs, { type CompactPaneTab } from "../components/ui/CompactPaneTabs";
import Popover from "../components/ui/Popover";
import EditorCentricLayout from "../layouts/EditorCentricLayout";
import ArtifactCredibilityLayer from "../components/artifacts/ArtifactCredibilityLayer";
import { resolveArtifactWorkflowActions, type WorkflowAction, type WorkflowActionId } from "../workflows/artifactWorkflow";
import { computeLineDiff } from "../utils/textDiff";
import { useNotifications } from "../state/notificationsStore";
import { useOperations } from "../state/operationRegistry";
import { useXynConsole } from "../state/xynConsoleStore";
import { canRewriteSelection, resolveAssistPrimaryAction } from "./articleAssistLogic";
import { applyPatchToFormSnapshot, buildArticleDraftSnapshot } from "../utils/articleIntentForm";

type ActivityTab = "overview" | "revisions" | "surfaces" | "raw" | "ai_config" | "discussion";
type RevisionMode = "list" | "view" | "diff";
type EditorMode = "edit" | "review";
type VideoTab = "scenes" | "script" | "storyboard" | "renders";
const REVIEW_TOAST_ACTION = "article.ai.review";
const EXPLAINER_PURPOSE_META = [
  { slug: "explainer_script", name: "Script", description: "Narration draft generation." },
  { slug: "explainer_storyboard", name: "Storyboard", description: "Scene structure generation." },
  { slug: "explainer_visual_prompts", name: "Visual Prompts", description: "Scene-by-scene prompt generation." },
  { slug: "explainer_narration", name: "Narration", description: "Spoken rewrite refinement." },
  { slug: "explainer_title_description", name: "Title/Description", description: "Title, description, CTA variants." },
] as const;
type ExplainerPurposeSlug = (typeof EXPLAINER_PURPOSE_META)[number]["slug"];
type VideoContextPackOverride = {
  mode?: "extend" | "replace";
  context_pack_refs?: unknown[];
};

type PendingAssist = {
  mode: "generate_draft" | "propose_edits" | "rewrite_selection";
  body: string;
  provider?: string;
  model?: string;
  agent_slug?: string;
};

type EditorSelection = {
  selectedText: string;
  contextBefore: string;
  contextAfter: string;
  anchorRect?: {
    top: number;
    left: number;
    width: number;
    height: number;
  };
};

type RefinementSurface = "article" | "script" | "storyboard";

type StoryboardFieldKey = "on_screen_text" | "visual_description" | "narration";

type StoryboardSelection = EditorSelection & {
  field: StoryboardFieldKey;
  sceneIndex: number;
};

type PendingSurfaceRefinement = {
  surface: "script" | "storyboard";
  mode: "propose_edits" | "rewrite_selection";
  baseText: string;
  nextText: string;
  storyboardField?: StoryboardFieldKey;
  storyboardSceneIndex?: number;
  provider?: string;
  model?: string;
  agent_slug?: string;
};

function actionGroupLabel(group: WorkflowAction["group"]): string {
  if (group === "position") return "Reactions";
  if (group === "workflow") return "Workflow";
  if (group === "danger") return "Lifecycle";
  return "Other";
}

function createDefaultVideoSpec(title: string, summaryText: string): VideoSpec {
  return {
    version: 1,
    title,
    intent: summaryText || "",
    audience: "mixed",
    tone: "clear, confident, warm",
    duration_seconds_target: 150,
    voice: {
      style: "conversational",
      speaker: "neutral",
      pace: "medium",
    },
    script: {
      draft: "",
      last_generated_at: null,
      notes: "",
      proposals: [],
    },
    storyboard: {
      draft: [],
      last_generated_at: null,
      notes: "",
      proposals: [],
    },
    scenes: [],
    generation: {
      provider: null,
      status: "not_started",
      last_render_id: null,
    },
  };
}

function buildSceneScaffold(title: string, intent: string, summaryText: string, sceneCount = 5): VideoSpec["scenes"] {
  const normalizedCount = Math.max(3, Math.min(7, sceneCount || 5));
  const core = (intent || summaryText || title || "Explainer").trim();
  const prompts = [
    { name: "Hook / Premise", onScreen: "What this is about", narration: `This explainer introduces ${core} in plain language.` },
    { name: "Setup / Context", onScreen: "The setup", narration: `First, we establish the context and why ${core} matters.` },
    { name: "Key Points", onScreen: "Key points", narration: `Next, we walk through the main points and concrete details.` },
    { name: "Outcome / Takeaways", onScreen: "What it means", narration: `Then we summarize the outcomes and practical takeaways.` },
    { name: "Close / Next Step", onScreen: "Closing thought", narration: `Finally, we close with the key next step for the audience.` },
    { name: "Deep Dive", onScreen: "Further detail", narration: `We add supporting detail to strengthen understanding.` },
    { name: "Wrap-up", onScreen: "Recap", narration: `We end with a concise recap of the full narrative.` },
  ];
  return Array.from({ length: normalizedCount }).map((_, index) => {
    const seed = prompts[index] || prompts[prompts.length - 1];
    return {
      id: `s${index + 1}`,
      name: seed.name,
      duration_seconds: 8,
      narration: seed.narration,
      visual_prompt: `${title || "Explainer"} visual support`,
      on_screen_text: seed.onScreen,
      camera_motion: "",
      style_constraints: [],
      generated: { image_asset_url: null, video_clip_url: null },
    };
  });
}

const PERSON_LIKENESS_PATTERNS: RegExp[] = [
  /\blooks?\s+like\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g,
  /\b(?:with|featuring)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g,
  /\bin\s+the\s+style\s+of\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g,
  /\b(celebrity|famous actor|famous person|real person(?:'s)? likeness)\b/gi,
];

function collectRenderPromptText(spec: VideoSpec | null): string {
  if (!spec) return "";
  const scenes = (spec.scenes || [])
    .map((scene) => [scene.name, scene.narration, scene.on_screen_text, scene.visual_prompt].filter(Boolean).join(" "))
    .join("\n");
  const storyboard = (spec.storyboard?.draft || [])
    .map((scene) =>
      [
        String(scene.on_screen_text || ""),
        String(scene.visual_description || ""),
        String(scene.narration || ""),
      ]
        .filter(Boolean)
        .join(" "),
    )
    .join("\n");
  return [spec.title || "", spec.intent || "", spec.script?.draft || "", scenes, storyboard].filter(Boolean).join("\n");
}

function lintPolicyRisk(text: string): string[] {
  const input = String(text || "");
  if (!input.trim()) return [];
  const hits: string[] = [];
  PERSON_LIKENESS_PATTERNS.forEach((pattern) => {
    const matches = input.match(pattern) || [];
    matches.forEach((match) => {
      const cleaned = String(match).trim();
      if (cleaned && !hits.includes(cleaned)) hits.push(cleaned);
    });
  });
  return hits;
}

function resolveVariantQueryToFormat(raw: string): ArticleFormat | null {
  const value = String(raw || "").trim().toLowerCase();
  if (!value) return null;
  if (value === "explainer_video" || value === "video_explainer") return "video_explainer";
  return "standard";
}

function neutralizePolicyRiskText(text: string): string {
  let next = String(text || "");
  next = next.replace(/\blooks?\s+like\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g, "has a generic appearance");
  next = next.replace(/\b(?:with|featuring)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g, "with a generic person");
  next = next.replace(/\bin\s+the\s+style\s+of\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+/g, "in a neutral style");
  next = next.replace(/\b(celebrity|famous actor|famous person|real person(?:'s)? likeness)\b/gi, "generic person");
  return next;
}

function neutralizeVideoSpecPolicyRisk(spec: VideoSpec | null): VideoSpec | null {
  if (!spec) return spec;
  return {
    ...spec,
    title: neutralizePolicyRiskText(spec.title || ""),
    intent: neutralizePolicyRiskText(spec.intent || ""),
    script: {
      ...(spec.script || { draft: "" }),
      draft: neutralizePolicyRiskText(spec.script?.draft || ""),
    },
    scenes: (spec.scenes || []).map((scene) => ({
      ...scene,
      name: neutralizePolicyRiskText(scene.name || ""),
      narration: neutralizePolicyRiskText(scene.narration || ""),
      on_screen_text: neutralizePolicyRiskText(scene.on_screen_text || ""),
      visual_prompt: neutralizePolicyRiskText(scene.visual_prompt || ""),
    })),
    storyboard: {
      ...(spec.storyboard || { draft: [] }),
      draft: (spec.storyboard?.draft || []).map((scene) => ({
        ...scene,
        on_screen_text: neutralizePolicyRiskText(String(scene.on_screen_text || "")),
        visual_description: neutralizePolicyRiskText(String(scene.visual_description || "")),
        narration: neutralizePolicyRiskText(String(scene.narration || "")),
      })),
    },
  };
}

export default function ArtifactDetailPage({
  workspaceId,
  workspaceRole,
  canManageArticleLifecycle,
}: {
  workspaceId: string;
  workspaceRole: string;
  canManageArticleLifecycle: boolean;
}) {
  const params = useParams();
  const location = useLocation();
  const artifactId = useMemo(() => {
    const direct = String(params.artifactId || "").trim();
    if (direct) return direct;
    const fromSurfaceRoute = location.pathname.match(/^\/app\/a\/(?:articles|workflows)\/([^/?#]+)/i)?.[1];
    return decodeURIComponent(String(fromSurfaceRoute || "").trim());
  }, [location.pathname, params.artifactId]);
  const surfaceVariantOverride = useMemo(
    () => resolveVariantQueryToFormat(new URLSearchParams(location.search).get("variant") || ""),
    [location.search]
  );
  const [item, setItem] = useState<ArticleDetail | null>(null);
  const [title, setTitle] = useState("");
  const [revisions, setRevisions] = useState<ArticleRevision[]>([]);
  const [artifactSurfaces, setArtifactSurfaces] = useState<ArtifactSurface[]>([]);
  const [artifactRuntimeRoles, setArtifactRuntimeRoles] = useState<ArtifactRuntimeRole[]>([]);
  const [bodyMarkdown, setBodyMarkdown] = useState("");
  const [legacyBodyHtml, setLegacyBodyHtml] = useState("");
  const [summary, setSummary] = useState("");
  const [articleFormat, setArticleFormat] = useState<ArticleFormat>("standard");
  const [category, setCategory] = useState<string>("web");
  const [visibilityType, setVisibilityType] = useState<"public" | "authenticated" | "role_based" | "private">("private");
  const [allowedRolesText, setAllowedRolesText] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [categoryOptions, setCategoryOptions] = useState<Array<{ slug: string; name: string; enabled: boolean }>>([]);
  const [commentBody, setCommentBody] = useState("");
  const [assistAgents, setAssistAgents] = useState<Array<{ id: string; slug: string; name: string }>>([]);
  const [selectedAgent, setSelectedAgent] = useState("");
  const [assistInstruction, setAssistInstruction] = useState("");
  const [assistBusy, setAssistBusy] = useState(false);
  const [summaryBusy, setSummaryBusy] = useState(false);
  const [busyActionId, setBusyActionId] = useState<WorkflowActionId | null>(null);
  const [confirmingAction, setConfirmingAction] = useState<WorkflowAction | null>(null);
  const [draftBarActionsOpen, setDraftBarActionsOpen] = useState(false);
  const [restoreRevisionId, setRestoreRevisionId] = useState<string | null>(null);
  const [activityTab, setActivityTab] = useState<ActivityTab>("revisions");
  const [canDebugRaw, setCanDebugRaw] = useState(false);
  const [rawAccessKnown, setRawAccessKnown] = useState(false);
  const [rawMeta, setRawMeta] = useState<ArtifactRawMetadataResponse | null>(null);
  const [rawArtifactJson, setRawArtifactJson] = useState<Record<string, unknown> | null>(null);
  const [rawEntries, setRawEntries] = useState<RawFileEntry[]>([]);
  const [rawPath, setRawPath] = useState("/");
  const [rawSelectedPath, setRawSelectedPath] = useState("/artifact.json");
  const [rawPreview, setRawPreview] = useState<Record<string, unknown> | null>(null);
  const [rawError, setRawError] = useState<string | null>(null);
  const [rawLoading, setRawLoading] = useState(false);
  const [rawLoadedFor, setRawLoadedFor] = useState<string>("");
  const [revisionMode, setRevisionMode] = useState<RevisionMode>("list");
  const [selectedRevisionId, setSelectedRevisionId] = useState<string>("");
  const [compareRevisionId, setCompareRevisionId] = useState<string>("current");
  const [baselineBody, setBaselineBody] = useState("");
  const [baselineLabel, setBaselineLabel] = useState("latest saved revision");
  const [showPreview, setShowPreview] = useState(false);
  const [editorMode, setEditorMode] = useState<EditorMode>("edit");
  const [videoTab, setVideoTab] = useState<VideoTab>("scenes");
  const [articleEditorCollapsed, setArticleEditorCollapsed] = useState(false);
  const [videoPanelCollapsed, setVideoPanelCollapsed] = useState(false);
  const [videoSpec, setVideoSpec] = useState<VideoSpec | null>(null);
  const [videoRenders, setVideoRenders] = useState<VideoRender[]>([]);
  const [videoRenderingMode, setVideoRenderingMode] = useState<string>("");
  const [videoContextPacks, setVideoContextPacks] = useState<ContextPackSummary[]>([]);
  const [selectedVideoContextPackId, setSelectedVideoContextPackId] = useState("");
  const [videoAiConfigOverrides, setVideoAiConfigOverrides] = useState<{
    agents: Record<string, string>;
    context_packs: Record<string, VideoContextPackOverride | unknown>;
  }>({
    agents: {},
    context_packs: {},
  });
  const [videoAiConfigDraft, setVideoAiConfigDraft] = useState<{
    agents: Record<string, string>;
    context_packs: Record<string, VideoContextPackOverride | unknown>;
  }>({
    agents: {},
    context_packs: {},
  });
  const [videoAiConfigEffective, setVideoAiConfigEffective] = useState<Record<string, VideoAiConfigEntry>>({});
  const [videoPurposeAgents, setVideoPurposeAgents] = useState<Record<string, AiAgent[]>>({});
  const [videoPurposeContextPacks, setVideoPurposeContextPacks] = useState<Record<string, ContextPackSummary[]>>({});
  const [videoAiConfigBusy, setVideoAiConfigBusy] = useState(false);
  const [videoBusy, setVideoBusy] = useState<"init" | "save" | "script" | "storyboard" | "render" | "retry" | "cancel" | null>(null);
  const [selectedVideoSceneIndex, setSelectedVideoSceneIndex] = useState(0);
  const [sceneRegenerateOpen, setSceneRegenerateOpen] = useState(false);
  const [sceneRegenerateProposal, setSceneRegenerateProposal] = useState<VideoSpec["scenes"]>([]);
  const [selectedStoryboardSceneIndex, setSelectedStoryboardSceneIndex] = useState(0);
  const [pendingAssist, setPendingAssist] = useState<PendingAssist | null>(null);
  const [pendingSurfaceRefinement, setPendingSurfaceRefinement] = useState<PendingSurfaceRefinement | null>(null);
  const [editorSelection, setEditorSelection] = useState<EditorSelection | null>(null);
  const [scriptSelection, setScriptSelection] = useState<EditorSelection | null>(null);
  const [storyboardSelection, setStoryboardSelection] = useState<StoryboardSelection | null>(null);
  const [selectionSurface, setSelectionSurface] = useState<RefinementSurface | null>(null);
  const [refinementOpen, setRefinementOpen] = useState(false);
  const [refinementSurface, setRefinementSurface] = useState<RefinementSurface>("article");
  const [refinementAnchorRect, setRefinementAnchorRect] = useState<EditorSelection["anchorRect"] | null>(null);
  const [editorFocusSignal, setEditorFocusSignal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const { push } = useNotifications();
  const { startOperation, finishOperation } = useOperations();
  const {
    session: consoleSession,
    setContext: setConsoleContext,
    clearContext: clearConsoleContext,
    registerEditorBridge,
    unregisterEditorBridge,
  } = useXynConsole();
  const videoPanelRef = useRef<HTMLElement | null>(null);
  const articleEditorCollapseInitializedForRef = useRef<string>("");
  const videoIntentFieldRef = useRef<HTMLTextAreaElement | null>(null);
  const videoDurationFieldRef = useRef<HTMLInputElement | null>(null);
  const titleFieldRef = useRef<HTMLInputElement | null>(null);
  const formatFieldRef = useRef<HTMLSelectElement | null>(null);
  const categorySelectFieldRef = useRef<HTMLSelectElement | null>(null);
  const categoryInputFieldRef = useRef<HTMLInputElement | null>(null);
  const tagsFieldRef = useRef<HTMLInputElement | null>(null);
  const summaryFieldRef = useRef<HTMLTextAreaElement | null>(null);

  const parseCsv = useCallback(
    (value: string): string[] =>
      value
        .split(",")
        .map((entry) => entry.trim())
        .filter(Boolean),
    []
  );

  useEffect(() => {
    if (!artifactId) return;
    setConsoleContext({ artifact_id: artifactId, artifact_type: "ArticleDraft" });
    return () => {
      clearConsoleContext();
    };
  }, [artifactId, setConsoleContext, clearConsoleContext]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const profile = await getMe();
        if (!active) return;
        const permissions = profile.permissions || [];
        const roles = profile.roles || [];
        const allowed =
          permissions.includes("artifact_debug_view") ||
          roles.includes("platform_admin") ||
          roles.includes("platform_architect");
        setCanDebugRaw(Boolean(allowed));
      } catch {
        if (!active) return;
        setCanDebugRaw(false);
      } finally {
        if (active) setRawAccessKnown(true);
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const handleEditorSelectionChange = useCallback((selection: EditorSelectionPayload) => {
    setEditorSelection(selection);
    if (selection?.selectedText?.trim()) {
      setSelectionSurface("article");
      setRefinementSurface("article");
      setRefinementAnchorRect(selection.anchorRect || null);
    } else if (selectionSurface === "article") {
      setSelectionSurface(null);
    }
  }, [selectionSurface]);

  const applyRewriteSelection = useCallback((source: string, selectedText: string, rewrittenText: string): string => {
    if (!selectedText.trim()) return source;
    const directIndex = source.indexOf(selectedText);
    if (directIndex >= 0) {
      return `${source.slice(0, directIndex)}${rewrittenText}${source.slice(directIndex + selectedText.length)}`;
    }
    const escaped = selectedText.trim().replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+");
    const fuzzyMatch = source.match(new RegExp(escaped));
    if (fuzzyMatch && fuzzyMatch.index !== undefined) {
      return `${source.slice(0, fuzzyMatch.index)}${rewrittenText}${source.slice(fuzzyMatch.index + fuzzyMatch[0].length)}`;
    }
    throw new Error("Could not map the selected text into markdown. Try selecting a slightly larger span.");
  }, []);

  const extractTextareaSelection = useCallback((element: HTMLTextAreaElement): EditorSelection | null => {
    const start = element.selectionStart ?? 0;
    const end = element.selectionEnd ?? 0;
    if (end <= start) return null;
    const selectedText = element.value.slice(start, end);
    if (!selectedText.trim()) return null;
    const radius = 600;
    const contextBefore = element.value.slice(Math.max(0, start - radius), start);
    const contextAfter = element.value.slice(end, Math.min(element.value.length, end + radius));
    const rect = element.getBoundingClientRect();
    return {
      selectedText,
      contextBefore,
      contextAfter,
      anchorRect: {
        top: rect.top + 8,
        left: rect.left + Math.min(rect.width * 0.5, 220),
        width: 1,
        height: 1,
      },
    };
  }, []);

  const handleStoryboardSelection = useCallback(
    (element: HTMLTextAreaElement, field: StoryboardFieldKey, sceneIndex: number) => {
      const selection = extractTextareaSelection(element);
      if (!selection) {
        setStoryboardSelection(null);
        if (selectionSurface === "storyboard") setSelectionSurface(null);
        return;
      }
      const payload: StoryboardSelection = { ...selection, field, sceneIndex };
      setStoryboardSelection(payload);
      setSelectionSurface("storyboard");
      setRefinementSurface("storyboard");
      setRefinementAnchorRect(payload.anchorRect || null);
    },
    [extractTextareaSelection, selectionSurface]
  );

  const loadVideoContextPacks = useCallback(async () => {
    const data = await listContextPacks({ purpose: "video_explainer", active: true });
    const packs = data.context_packs || [];
    setVideoContextPacks(packs);
    return packs;
  }, []);

  const loadVideoAiConfig = useCallback(async () => {
    if (!artifactId) return;
    const data = await getArticleVideoAiConfig(artifactId);
    const overrides = {
      agents: data.overrides?.agents || {},
      context_packs: data.overrides?.context_packs || {},
    };
    setVideoAiConfigOverrides(overrides);
    setVideoAiConfigDraft(overrides);
    setVideoAiConfigEffective(data.effective || {});
  }, [artifactId]);

  const loadVideoAiConfigOptions = useCallback(async () => {
    const purposes = EXPLAINER_PURPOSE_META.map((item) => item.slug);
    const [agentsResults, packsResults] = await Promise.all([
      Promise.all(purposes.map((purpose) => listAiAgents({ purpose, enabled: true }))),
      Promise.all(purposes.map((purpose) => listContextPacks({ purpose, active: true }))),
    ]);
    const nextAgents: Record<string, AiAgent[]> = {};
    const nextPacks: Record<string, ContextPackSummary[]> = {};
    purposes.forEach((purpose, index) => {
      nextAgents[purpose] = agentsResults[index]?.agents || [];
      nextPacks[purpose] = packsResults[index]?.context_packs || [];
    });
    setVideoPurposeAgents(nextAgents);
    setVideoPurposeContextPacks(nextPacks);
  }, []);

  const loadRawArtifactView = useCallback(async () => {
    if (!artifactId || !canDebugRaw) return;
    setRawLoading(true);
    setRawError(null);
    try {
      const [meta, artifactJson, files] = await Promise.all([
        getArtifactRawMetadata(artifactId),
        getArtifactRawArtifactJson(artifactId),
        listArtifactRawFiles(artifactId, "/"),
      ]);
      setRawMeta(meta);
      setRawArtifactJson(artifactJson);
      setRawEntries(files.entries || []);
      setRawPath(files.path || "/");
      setRawSelectedPath("/artifact.json");
      setRawPreview({ inline: true, content: JSON.stringify(artifactJson || {}, null, 2), path: "/artifact.json" });
      setRawLoadedFor(artifactId);
    } catch (err) {
      setRawError((err as Error).message);
    } finally {
      setRawLoading(false);
    }
  }, [artifactId, canDebugRaw]);

  const openRawPath = useCallback(
    async (entry: RawFileEntry) => {
      if (!artifactId || !canDebugRaw) return;
      if (entry.kind === "dir") {
        const next = await listArtifactRawFiles(artifactId, entry.path);
        setRawEntries(next.entries || []);
        setRawPath(next.path || "/");
        return;
      }
      setRawSelectedPath(entry.path);
      const preview = await getArtifactRawFilePreview(artifactId, entry.path);
      setRawPreview(preview as unknown as Record<string, unknown>);
    },
    [artifactId, canDebugRaw]
  );

  const load = useCallback(async () => {
    if (!artifactId || !workspaceId) return;
    try {
      setError(null);
      let resolvedArticleId = artifactId;
      try {
        const artifactRecord = await getArtifact(artifactId);
        const artifactType = String(artifactRecord.artifact_type || "").trim().toLowerCase();
        if (artifactType && artifactType !== "article") {
          throw new Error(`Artifact type '${artifactType}' is not supported in the Article editor.`);
        }
        const source = ((artifactRecord.source || {}) as Record<string, unknown>) || {};
        const sourceId = String(source.id || artifactRecord.source_ref_id || "").trim();
        if (sourceId) {
          resolvedArticleId = sourceId;
        }
      } catch (artifactErr) {
        const message = String((artifactErr as Error)?.message || "");
        if (message.toLowerCase().includes("not supported in the article editor")) {
          throw artifactErr;
        }
        // Fall back to direct article lookup for legacy IDs/routes.
      }
      const [articleRes, revisionsRes, categoriesRes] = await Promise.all([
        getArticle(resolvedArticleId),
        listArticleRevisions(resolvedArticleId),
        listArticleCategories(),
      ]);
      try {
        const [surfacesRes, runtimeRolesRes] = await Promise.all([
          listArtifactSurfaces(artifactId),
          listArtifactRuntimeRoles(artifactId),
        ]);
        setArtifactSurfaces(surfacesRes.surfaces || []);
        setArtifactRuntimeRoles(runtimeRolesRes.runtime_roles || []);
      } catch {
        setArtifactSurfaces([]);
        setArtifactRuntimeRoles([]);
      }
      const article = articleRes.article;
      const nextRevisions = revisionsRes.revisions || [];
      const latestRevision = nextRevisions[0];
      const initialBody = article.body_markdown || latestRevision?.body_markdown || "";
      const fallbackHtml = article.body_html || latestRevision?.body_html || "";
      setItem(article);
      setTitle(article.title || "");
      setRevisions(nextRevisions);
      setBodyMarkdown(initialBody);
      setLegacyBodyHtml(fallbackHtml);
      setSummary(article.summary || "");
      const nextFormat = surfaceVariantOverride || (article.format as ArticleFormat) || "standard";
      setArticleFormat(nextFormat);
      if (artifactId && articleEditorCollapseInitializedForRef.current !== artifactId) {
        setArticleEditorCollapsed(nextFormat === "video_explainer");
        articleEditorCollapseInitializedForRef.current = artifactId;
      }
      setVideoSpec(article.video_spec_json ? (article.video_spec_json as VideoSpec) : createDefaultVideoSpec(article.title || "", article.summary || ""));
      if (nextFormat === "video_explainer") {
        const [renderData, packsData] = await Promise.all([
          listArticleVideoRenders(resolvedArticleId),
          loadVideoContextPacks(),
        ]);
        try {
          const platform = await getPlatformConfig();
          const mode = String(
            platform?.config?.video?.rendering_mode ||
              platform?.config?.video_generation?.provider ||
              ""
          ).trim();
          setVideoRenderingMode(mode);
        } catch {
          setVideoRenderingMode("");
        }
        await Promise.all([loadVideoAiConfig(), loadVideoAiConfigOptions()]);
        setVideoRenders(renderData.renders || []);
        setVideoContextPacks(packsData || []);
        const fallbackDefaultPackId = (packsData || []).find((pack) => pack.is_default)?.id || "";
        setSelectedVideoContextPackId(article.video_context_pack_id || fallbackDefaultPackId || "");
      } else {
        setVideoRenders([]);
        setVideoRenderingMode("");
        setVideoContextPacks([]);
        setSelectedVideoContextPackId("");
        setVideoAiConfigOverrides({ agents: {}, context_packs: {} });
        setVideoAiConfigDraft({ agents: {}, context_packs: {} });
        setVideoAiConfigEffective({});
        setVideoPurposeAgents({});
        setVideoPurposeContextPacks({});
      }
      setCategory(article.category || "web");
      setVisibilityType(article.visibility_type || "private");
      setAllowedRolesText((article.allowed_roles || []).join(", "));
      setTagsText((article.tags || []).join(", "));
      setCategoryOptions(
        (categoriesRes.categories || []).map((entry) => ({ slug: entry.slug, name: entry.name, enabled: Boolean(entry.enabled) }))
      );
      setBaselineBody(initialBody);
      setBaselineLabel(latestRevision ? `r${latestRevision.revision_number}` : "latest saved revision");
      setPendingAssist(null);
      setEditorMode("edit");
      if (latestRevision?.id) {
        setSelectedRevisionId(latestRevision.id);
      }
    } catch (err) {
      setError((err as Error).message);
    }
  }, [workspaceId, artifactId, loadVideoContextPacks, loadVideoAiConfig, loadVideoAiConfigOptions, surfaceVariantOverride]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (articleFormat !== "video_explainer") return;
    if (selectedVideoContextPackId) return;
    const defaultPack = videoContextPacks.find((pack) => pack.is_default);
    if (defaultPack?.id) {
      setSelectedVideoContextPackId(defaultPack.id);
    }
  }, [articleFormat, selectedVideoContextPackId, videoContextPacks]);

  useEffect(() => {
    const onToastAction = (event: Event) => {
      const detail = (event as CustomEvent<{ action?: string }>).detail || {};
      if (detail.action !== REVIEW_TOAST_ACTION) return;
      if (!pendingAssist) return;
      setEditorMode("review");
      setEditorFocusSignal((current) => current + 1);
    };
    window.addEventListener("xyn:notification-action", onToastAction as EventListener);
    return () => window.removeEventListener("xyn:notification-action", onToastAction as EventListener);
  }, [pendingAssist]);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const data = await listAiAgents({ purpose: "documentation", enabled: true });
        if (!mounted) return;
        const options = (data.agents || []).map((entry) => ({ id: entry.id, slug: entry.slug, name: entry.name }));
        setAssistAgents(options);
        if (!selectedAgent && options.length) {
          const stored = localStorage.getItem("xyn.articleAiAgentSlug") || "";
          setSelectedAgent(options.find((entry) => entry.slug === stored)?.slug || options[0].slug);
        }
      } catch {
        if (!mounted) return;
        setAssistAgents([]);
      }
    })();
    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

  useEffect(() => {
    if (!artifactId || articleFormat !== "video_explainer") return;
    const hasRunning = videoRenders.some((entry) => entry.status === "queued" || entry.status === "running");
    if (!hasRunning) return;
    const timer = window.setInterval(async () => {
      try {
        const rows = await listArticleVideoRenders(artifactId);
        setVideoRenders(rows.renders || []);
      } catch {
        // Ignore polling hiccups; explicit actions still surface errors.
      }
    }, 4000);
    return () => window.clearInterval(timer);
  }, [artifactId, articleFormat, videoRenders]);

  useEffect(() => {
    if (articleFormat !== "video_explainer" && activityTab === "ai_config") {
      setActivityTab("revisions");
    }
  }, [activityTab, articleFormat]);

  useEffect(() => {
    if (activityTab !== "raw") return;
    if (!canDebugRaw) return;
    if (!artifactId) return;
    if (rawLoadedFor === artifactId) return;
    void loadRawArtifactView();
  }, [activityTab, artifactId, canDebugRaw, loadRawArtifactView, rawLoadedFor]);

  useEffect(() => {
    if (videoTab !== "script") setScriptSelection(null);
    if (videoTab !== "storyboard") setStoryboardSelection(null);
  }, [videoTab]);

  const save = async () => {
    if (!artifactId) return;
    try {
      setError(null);
      await updateArticle(artifactId, {
        title: title.trim(),
        format: articleFormat,
        category,
        visibility_type: visibilityType,
        allowed_roles: visibilityType === "role_based" ? parseCsv(allowedRolesText) : [],
        tags: parseCsv(tagsText),
        video_spec_json: articleFormat === "video_explainer" ? videoSpec : null,
        video_context_pack_id: articleFormat === "video_explainer" ? selectedVideoContextPackId || null : null,
      });
      await createArticleRevision(artifactId, {
        summary,
        body_markdown: bodyMarkdown,
        tags: parseCsv(tagsText),
        source: "manual",
      });
      await load();
      push({
        level: "success",
        title: "Revision saved",
        message: "Saved as new revision.",
        status: "succeeded",
        action: "article.save",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const convertLegacyHtml = async () => {
    if (!artifactId) return;
    try {
      setError(null);
      const result = await convertArticleHtmlToMarkdown(artifactId);
      if (result.converted) {
        push({
          level: "success",
          title: "Converted to markdown",
          message: "Created a new revision from legacy HTML.",
          status: "succeeded",
          action: "article.convert_html",
          entityType: "unknown",
          entityId: artifactId,
        });
      } else {
        push({
          level: "info",
          title: "No conversion needed",
          message: result.reason === "already_markdown" ? "Article already has markdown content." : "No conversion was needed.",
          status: "succeeded",
          action: "article.convert_html",
          entityType: "unknown",
          entityId: artifactId,
        });
      }
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const runAssist = async (mode: "generate_draft" | "propose_edits" | "rewrite_selection", surface: RefinementSurface = "article") => {
    if (!artifactId) return;
    if (!selectedAgent) {
      setError("No refinement agent selected. Configure one in Platform -> AI Agents.");
      return;
    }
    const surfaceSelection = surface === "article" ? editorSelection : surface === "script" ? scriptSelection : storyboardSelection;
    if ((mode === "rewrite_selection" || (isExplainerFormat && mode === "propose_edits")) && !surfaceSelection) return;
    const opId = `${artifactId}:${surface}:${mode}:${Date.now()}`;
    startOperation({
      id: opId,
      type: "ai",
      label: mode === "generate_draft" ? "Generate draft" : mode === "propose_edits" ? "Suggest edits" : "Rewrite selection",
      entityType: "article",
      entityId: artifactId,
    });
    try {
      setError(null);
      setAssistBusy(true);
      push({
        level: "info",
        title: "AI thinking",
        message: "Generating proposal…",
        status: "queued",
        action: "article.ai",
        entityType: "unknown",
        entityId: artifactId,
        dedupeKey: `article-ai:${artifactId}:${surface}:${mode}`,
      });
      localStorage.setItem("xyn.articleAiAgentSlug", selectedAgent);
      const surfaceBody =
        surface === "article"
          ? bodyMarkdown
          : surface === "script"
            ? String(activeVideoSpec.script?.draft || "")
            : (() => {
                if (!storyboardSelection) return "";
                const scene = (activeVideoSpec.storyboard?.draft || [])[storyboardSelection.sceneIndex];
                if (!scene) return "";
                return String(scene[storyboardSelection.field] || "");
              })();
      const prompt =
        mode === "generate_draft"
          ? `Draft article content from this idea. Return markdown only. Idea:\n${assistInstruction || summary || item?.title || ""}`
          : surfaceSelection && (mode === "rewrite_selection" || (isExplainerFormat && mode === "propose_edits"))
            ? [
                mode === "rewrite_selection"
                  ? "Rewrite only the selected region and preserve all intent."
                  : "Suggest improvements for only the selected region and preserve all intent.",
                "Return only the rewritten selected text. Do not include markdown fences or commentary.",
                `Surface: ${surface}`,
                `Instruction: ${assistInstruction || "Improve clarity and flow while preserving meaning."}`,
                ...(isExplainerFormat
                  ? [
                      "Explainer video context (canonical goals):",
                      explainerRefinementContext,
                    ]
                  : []),
                "Selected text:",
                surfaceSelection.selectedText,
                "Context before:",
                surfaceSelection.contextBefore,
                "Context after:",
                surfaceSelection.contextAfter,
              ].join("\n\n")
            : `Suggest edits and provide an improved markdown version.\n\nInstruction: ${assistInstruction || "Improve clarity and readability."}\n\n${surfaceBody}`;
      const modeForApi = mode === "generate_draft" ? "draft" : mode === "rewrite_selection" ? "rewrite" : "edits";
      const result = await invokeAi({
        agent_slug: selectedAgent,
        messages: [{ role: "user", content: prompt }],
        metadata: { feature: "articles_ai_assist", artifact_id: artifactId, workspace_id: workspaceId, mode: modeForApi, surface },
      });
      const rawBody = String(result.content || "").trim();
      if (!rawBody) throw new Error("AI returned empty content.");
      const nextText =
        surfaceSelection && (mode === "rewrite_selection" || (isExplainerFormat && mode === "propose_edits"))
          ? applyRewriteSelection(surfaceBody, surfaceSelection.selectedText, rawBody)
          : rawBody;
      if (surface === "article") {
        setPendingAssist({
          mode,
          body: nextText,
          provider: result.provider,
          model: result.model,
          agent_slug: result.agent_slug,
        });
        setEditorMode("review");
      } else {
        setPendingSurfaceRefinement({
          surface,
          mode: mode === "rewrite_selection" ? "rewrite_selection" : "propose_edits",
          baseText: surfaceBody,
          nextText,
          storyboardField: surface === "storyboard" ? storyboardSelection?.field : undefined,
          storyboardSceneIndex: surface === "storyboard" ? storyboardSelection?.sceneIndex : undefined,
          provider: result.provider,
          model: result.model,
          agent_slug: result.agent_slug,
        });
      }
      setRefinementOpen(false);
      finishOperation({
        id: opId,
        status: "succeeded",
        summary: "AI suggestion ready",
      });
      push({
        level: "success",
        title: "AI suggestion ready",
        message: "Review changes in editor.",
        status: "succeeded",
        action: "article.ai",
        entityType: "unknown",
        entityId: artifactId,
        ctaLabel: surface === "article" ? "Review changes" : undefined,
        ctaAction: surface === "article" ? REVIEW_TOAST_ACTION : undefined,
        dedupeKey: `article-ai:${artifactId}:${surface}:${mode}`,
      });
    } catch (err) {
      finishOperation({
        id: opId,
        status: "failed",
        summary: (err as Error).message,
      });
      push({
        level: "error",
        title: "AI assist failed",
        message: (err as Error).message,
        status: "failed",
        action: "article.ai",
        entityType: "unknown",
        entityId: artifactId,
      });
      setError((err as Error).message);
    } finally {
      setAssistBusy(false);
    }
  };

  const summarizeWithAi = async () => {
    if (!artifactId) return;
    if (!selectedAgent) {
      setError("No documentation agent selected. Configure one in Platform -> AI -> Agents.");
      return;
    }

    const opId = `${artifactId}:summarize:${Date.now()}`;
    startOperation({
      id: opId,
      type: "ai",
      label: "Summarize article",
      entityType: "article",
      entityId: artifactId,
    });

    try {
      setError(null);
      setSummaryBusy(true);
      localStorage.setItem("xyn.articleAiAgentSlug", selectedAgent);
      const prompt = [
        "Create a concise summary of this article in 1-2 sentences.",
        "Return plain text only. Do not include bullets, markdown, headings, or quotation marks.",
        "If an existing summary is provided, improve and replace it.",
        `Title: ${item?.title || ""}`,
        `Existing summary: ${summary || "(none)"}`,
        "Article markdown:",
        bodyMarkdown || "(empty)",
      ].join("\n\n");
      const result = await invokeAi({
        agent_slug: selectedAgent,
        messages: [{ role: "user", content: prompt }],
        metadata: { feature: "articles_ai_assist", artifact_id: artifactId, workspace_id: workspaceId, mode: "summarize" },
      });
      const nextSummary = String(result.content || "")
        .replace(/\s+/g, " ")
        .trim();
      if (!nextSummary) throw new Error("AI returned empty content.");
      setSummary(nextSummary);
      finishOperation({
        id: opId,
        status: "succeeded",
        summary: "Summary updated",
      });
      push({
        level: "success",
        title: "Summary updated",
        message: "AI generated a new summary.",
        status: "succeeded",
        action: "article.ai.summarize",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      finishOperation({
        id: opId,
        status: "failed",
        summary: (err as Error).message,
      });
      setError((err as Error).message);
    } finally {
      setSummaryBusy(false);
    }
  };

  const persistVideoSpec = async (nextSpec: VideoSpec) => {
    if (!artifactId) return;
    try {
      setVideoBusy("save");
      setError(null);
      await updateArticle(artifactId, {
        format: "video_explainer",
        video_spec_json: nextSpec,
        video_context_pack_id: selectedVideoContextPackId || null,
      });
      setVideoSpec(nextSpec);
      setArticleFormat("video_explainer");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
    }
  };

  const ensureVideoInitialized = async () => {
    if (!artifactId) return;
    try {
      setVideoBusy("init");
      setError(null);
      const result = await initializeArticleVideo(artifactId);
      setItem(result.article);
      setTitle(result.article.title || "");
      setArticleFormat(result.article.format);
      setVideoSpec((result.article.video_spec_json as VideoSpec) || createDefaultVideoSpec(result.article.title || "", result.article.summary || ""));
      setSelectedVideoContextPackId(result.article.video_context_pack_id || "");
      const renderData = await listArticleVideoRenders(artifactId);
      setVideoRenders(renderData.renders || []);
      await loadVideoContextPacks();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
    }
  };

  const readOverridePackIds = useCallback((purposeSlug: string): string[] => {
    const raw = videoAiConfigDraft.context_packs?.[purposeSlug];
    if (!raw) return [];
    let values: unknown[] = [];
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const refs = (raw as VideoContextPackOverride).context_pack_refs;
      values = Array.isArray(refs) ? refs : [];
    } else {
      values = Array.isArray(raw) ? raw : [raw];
    }
    return values
      .map((entry) => {
        if (entry && typeof entry === "object") {
          return String((entry as { id?: string; context_pack_id?: string }).id || (entry as { context_pack_id?: string }).context_pack_id || "").trim();
        }
        return String(entry || "").trim();
      })
      .filter(Boolean);
  }, [videoAiConfigDraft.context_packs]);

  const readOverrideMode = useCallback((purposeSlug: string): "extend" | "replace" => {
    const raw = videoAiConfigDraft.context_packs?.[purposeSlug];
    if (raw && typeof raw === "object" && !Array.isArray(raw)) {
      const mode = String((raw as VideoContextPackOverride).mode || "").trim().toLowerCase();
      if (mode === "replace") return "replace";
    }
    return "extend";
  }, [videoAiConfigDraft.context_packs]);

  const setOverrideAgent = useCallback((purposeSlug: ExplainerPurposeSlug, value: string) => {
    setVideoAiConfigDraft((current) => {
      const next = {
        agents: { ...(current.agents || {}) },
        context_packs: { ...(current.context_packs || {}) },
      };
      if (!value) delete next.agents[purposeSlug];
      else next.agents[purposeSlug] = value;
      return next;
    });
  }, []);

  const setOverrideContextPacks = useCallback((purposeSlug: ExplainerPurposeSlug, packIds: string[]) => {
    setVideoAiConfigDraft((current) => {
      const next = {
        agents: { ...(current.agents || {}) },
        context_packs: { ...(current.context_packs || {}) },
      };
      const currentMode = (() => {
        const raw = current.context_packs?.[purposeSlug];
        if (raw && typeof raw === "object" && !Array.isArray(raw)) {
          const mode = String((raw as VideoContextPackOverride).mode || "").trim().toLowerCase();
          if (mode === "replace") return "replace";
        }
        return "extend";
      })();
      if (!packIds.length) {
        delete next.context_packs[purposeSlug];
      } else {
        next.context_packs[purposeSlug] = {
          mode: currentMode,
          context_pack_refs: packIds,
        } satisfies VideoContextPackOverride;
      }
      return next;
    });
  }, []);

  const setOverrideContextMode = useCallback((purposeSlug: ExplainerPurposeSlug, mode: "extend" | "replace") => {
    setVideoAiConfigDraft((current) => {
      const next = {
        agents: { ...(current.agents || {}) },
        context_packs: { ...(current.context_packs || {}) },
      };
      const raw = current.context_packs?.[purposeSlug];
      const refs = (() => {
        const values: unknown[] =
          raw && typeof raw === "object" && !Array.isArray(raw)
            ? (() => {
                const refs = (raw as VideoContextPackOverride).context_pack_refs;
                return Array.isArray(refs) ? refs : [];
              })()
            : Array.isArray(raw)
              ? raw
              : raw
                ? [raw]
                : [];
        return values
          .map((entry) => {
            if (entry && typeof entry === "object") return String((entry as { id?: string }).id || "").trim();
            return String(entry || "").trim();
          })
          .filter(Boolean);
      })();
      if (!refs.length) {
        delete next.context_packs[purposeSlug];
      } else {
        next.context_packs[purposeSlug] = {
          mode,
          context_pack_refs: refs,
        } satisfies VideoContextPackOverride;
      }
      return next;
    });
  }, []);

  const saveVideoAiConfig = useCallback(async () => {
    if (!artifactId) return;
    try {
      setVideoAiConfigBusy(true);
      setError(null);
      const result = await updateArticleVideoAiConfig(artifactId, {
        agents: videoAiConfigDraft.agents,
        context_packs: videoAiConfigDraft.context_packs,
      });
      const overrides = {
        agents: result.overrides?.agents || {},
        context_packs: result.overrides?.context_packs || {},
      };
      setVideoAiConfigOverrides(overrides);
      setVideoAiConfigDraft(overrides);
      setVideoAiConfigEffective(result.effective || {});
      setItem(result.article || null);
      setTitle(result.article?.title || "");
      push({
        level: "success",
        title: "AI config saved",
        message: "Explainer purpose agent and context defaults updated.",
        status: "succeeded",
        action: "article.video.ai_config.save",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      push({
        level: "error",
        title: "AI config failed",
        message,
        status: "failed",
        action: "article.video.ai_config.save",
        entityType: "unknown",
        entityId: artifactId,
      });
    } finally {
      setVideoAiConfigBusy(false);
    }
  }, [artifactId, push, videoAiConfigDraft.agents, videoAiConfigDraft.context_packs]);

  const resetVideoAiConfig = useCallback(async () => {
    if (!artifactId) return;
    try {
      setVideoAiConfigBusy(true);
      setError(null);
      const result = await updateArticleVideoAiConfig(artifactId, { reset_all: true });
      const overrides = {
        agents: result.overrides?.agents || {},
        context_packs: result.overrides?.context_packs || {},
      };
      setVideoAiConfigOverrides(overrides);
      setVideoAiConfigDraft(overrides);
      setVideoAiConfigEffective(result.effective || {});
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoAiConfigBusy(false);
    }
  }, [artifactId]);

  const generateVideoStoryboardDraft = async () => {
    if (!artifactId) return;
    try {
      setVideoBusy("storyboard");
      setError(null);
      const result = await generateArticleVideoStoryboard(artifactId, {
        context_pack_id: selectedVideoContextPackId || null,
      });
      setItem(result.article);
      setTitle(result.article.title || "");
      setVideoSpec((result.article.video_spec_json as VideoSpec) || null);
      setSelectedVideoContextPackId(result.article.video_context_pack_id || selectedVideoContextPackId || "");
      push({
        level: "success",
        title: "Storyboard proposal ready",
        message: "Generated outputs are provisional. Accept or refine.",
        status: "succeeded",
        action: "article.video.storyboard",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
    }
  };

  const openRegenerateScenesPreview = useCallback(() => {
    const baseSpec = videoSpec || createDefaultVideoSpec(title, summary);
    const nextScenes = buildSceneScaffold(title, baseSpec.intent || "", summary, (baseSpec.scenes || []).length || 5);
    setSceneRegenerateProposal(nextScenes);
    setSceneRegenerateOpen(true);
  }, [summary, title, videoSpec]);

  const applyRegeneratedScenes = useCallback(() => {
    setVideoSpec((prev) => {
      const base = prev || createDefaultVideoSpec(title, summary);
      return {
        ...base,
        scenes: sceneRegenerateProposal,
      };
    });
    setSelectedVideoSceneIndex(0);
    setSceneRegenerateOpen(false);
  }, [sceneRegenerateProposal, summary, title]);

  const requestVideoRender = async () => {
    if (!artifactId) return;
    try {
      setVideoBusy("render");
      setError(null);
      const lintHits = lintPolicyRisk(collectRenderPromptText(videoSpec));
      if (lintHits.length > 0) {
        push({
          level: "warning",
          title: "Prompt may be blocked by provider policy",
          message: `Detected potential real-person references: ${lintHits.slice(0, 3).join(", ")}.`,
          status: "failed",
          action: "article.video.render.lint",
          entityType: "unknown",
          entityId: artifactId,
        });
      }
      const result = await renderArticleVideo(artifactId, {
        context_pack_id: selectedVideoContextPackId || null,
        request_payload_json: {
          mode: "full_render",
          prompt_lint: { real_person_reference_hits: lintHits },
        },
      });
      setVideoRenders((prev) => [result.render, ...prev.filter((entry) => entry.id !== result.render.id)]);
      setItem(result.article);
      setTitle(result.article.title || "");
      setSelectedVideoContextPackId(result.article.video_context_pack_id || selectedVideoContextPackId || "");
      push({
        level: "info",
        title: "Render requested",
        message: "Video render job created.",
        status: "queued",
        action: "article.video.render",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
      if (artifactId) {
        const rows = await listArticleVideoRenders(artifactId);
        setVideoRenders(rows.renders || []);
      }
    }
  };

  const retryFailedRender = async (renderId: string) => {
    if (!artifactId) return;
    try {
      setVideoBusy("retry");
      setError(null);
      const result = await retryVideoRender(renderId);
      setVideoRenders((prev) => [result.render, ...prev.filter((entry) => entry.id !== result.render.id)]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
    }
  };

  const cancelRunningRender = async (renderId: string) => {
    if (!artifactId) return;
    try {
      setVideoBusy("cancel");
      setError(null);
      const result = await cancelVideoRender(renderId);
      setVideoRenders((prev) => prev.map((entry) => (entry.id === renderId ? result.render : entry)));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setVideoBusy(null);
    }
  };

  const acceptAssist = async () => {
    if (!artifactId || !pendingAssist) return;
    try {
      setError(null);
      await createArticleRevision(artifactId, {
        summary,
        body_markdown: pendingAssist.body,
        tags: parseCsv(tagsText),
        source: "ai",
        provenance_json: {
          agent_slug: pendingAssist.agent_slug,
          provider: pendingAssist.provider,
          model_name: pendingAssist.model,
          invoked_at: new Date().toISOString(),
          mode:
            pendingAssist.mode === "generate_draft"
              ? "draft"
              : pendingAssist.mode === "rewrite_selection"
                ? "rewrite"
                : "edits",
        },
      });
      setBodyMarkdown(pendingAssist.body);
      setPendingAssist(null);
      setEditorMode("edit");
      await load();
      push({
        level: "success",
        title: "AI changes applied",
        message: "Saved as a new revision.",
        status: "succeeded",
        action: "article.ai.apply",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const transition = async (status: "reviewed" | "ratified" | "published" | "deprecated") => {
    if (!artifactId) return;
    try {
      await transitionArticle(artifactId, status);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const react = async (value: "endorse" | "oppose" | "neutral") => {
    if (!artifactId) return;
    try {
      await reactToWorkspaceArtifact(workspaceId, artifactId, value);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const addComment = async () => {
    if (!artifactId || !commentBody.trim()) return;
    try {
      await commentOnWorkspaceArtifact(workspaceId, artifactId, { body: commentBody });
      setCommentBody("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const moderate = async (commentId: string, status: "hidden" | "deleted") => {
    if (!artifactId) return;
    try {
      await moderateWorkspaceComment(workspaceId, artifactId, commentId, status);
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const restoreRevision = async () => {
    if (!artifactId || !restoreRevisionId) return;
    const revision = revisions.find((entry) => entry.id === restoreRevisionId);
    if (!revision) return;
    try {
      setError(null);
      await createArticleRevision(artifactId, {
        summary: revision.summary || summary,
        body_markdown: revision.body_markdown,
        tags: parseCsv(tagsText),
        source: "restore",
        provenance_json: {
          restored_revision_id: revision.id,
          restored_revision_number: revision.revision_number,
          restored_at: new Date().toISOString(),
        },
      });
      setRestoreRevisionId(null);
      await load();
      push({
        level: "success",
        title: "Revision restored",
        message: `Restored r${revision.revision_number} as a new revision.`,
        status: "succeeded",
        action: "article.restore",
        entityType: "unknown",
        entityId: artifactId,
      });
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const selectedCategoryMeta = categoryOptions.find((entry) => entry.slug === category) || null;
  const isDeprecatedCategory = Boolean(selectedCategoryMeta && !selectedCategoryMeta.enabled);
  const selectableCategoryOptions = categoryOptions.filter((entry) => entry.enabled);
  const origin = typeof window !== "undefined" ? window.location.origin : "";
  const canSaveRevision = workspaceRole !== "reader";
  const canReact = workspaceRole !== "reader";
  const workflow = useMemo(
    () =>
      resolveArtifactWorkflowActions({
        artifactType: "article",
        article: {
          status: item?.status || "draft",
          visibility_type: visibilityType,
          allowed_roles: parseCsv(allowedRolesText),
          published_to: item?.published_to || [],
          summary,
          title: item?.title || "",
        },
        validation: {
          hasBodyMarkdown: Boolean(bodyMarkdown.trim()),
          hasSummary: Boolean(summary.trim()),
        },
        capabilities: {
          canManageLifecycle: canManageArticleLifecycle,
          canSaveRevision,
          canReact,
          canViewRevisions: true,
        },
      }),
    [allowedRolesText, bodyMarkdown, canManageArticleLifecycle, canReact, canSaveRevision, item?.published_to, item?.status, item?.title, summary, visibilityType]
  );
  const draftBarSecondaryActions = useMemo(
    () => workflow.secondaryActions.filter((action) => action.id !== "save_revision" && action.id !== "view_revisions"),
    [workflow.secondaryActions]
  );
  const draftBarActionGroups = useMemo(() => {
    const orderedGroups: WorkflowAction["group"][] = ["workflow", "position", "danger", "revision"];
    return orderedGroups
      .map((group) => ({
        group,
        label: actionGroupLabel(group),
        actions: draftBarSecondaryActions.filter((action) => action.group === group),
      }))
      .filter((entry) => entry.actions.length > 0);
  }, [draftBarSecondaryActions]);

  const selectedRevision = useMemo(
    () => revisions.find((entry) => entry.id === selectedRevisionId) || revisions[0] || null,
    [revisions, selectedRevisionId]
  );

  const comparisonRevision = useMemo(() => {
    if (!selectedRevision) return null;
    if (compareRevisionId === "current") {
      return {
        id: "current",
        revision_number: 0,
        body_markdown: bodyMarkdown,
        summary,
      } as ArticleRevision;
    }
    return revisions.find((entry) => entry.id === compareRevisionId) || null;
  }, [selectedRevision, compareRevisionId, revisions, bodyMarkdown, summary]);

  const selectedRevisionDiff = useMemo(() => {
    if (!selectedRevision || !comparisonRevision) return null;
    return computeLineDiff(selectedRevision.body_markdown || "", comparisonRevision.body_markdown || "");
  }, [selectedRevision, comparisonRevision]);

  const pendingAssistDiff = useMemo(() => {
    if (!pendingAssist) return null;
    return computeLineDiff(bodyMarkdown, pendingAssist.body);
  }, [bodyMarkdown, pendingAssist]);

  const drift = useMemo(() => computeLineDiff(baselineBody, bodyMarkdown), [baselineBody, bodyMarkdown]);
  const hasBodyContent = Boolean(bodyMarkdown.trim() || revisions.length > 0);
  const fallbackAssistAction = resolveAssistPrimaryAction(hasBodyContent);
  const activeSelection =
    selectionSurface === "script" ? scriptSelection : selectionSurface === "storyboard" ? storyboardSelection : editorSelection;
  const selectionLength = activeSelection?.selectedText.length || 0;
  const canRefineSelection = canRewriteSelection(selectionLength);
  const isExplainerFormat = articleFormat === "video_explainer";
  const activeVideoSpec = videoSpec || createDefaultVideoSpec(item?.title || "", summary || "");
  const renderPromptLintHits = useMemo(
    () => lintPolicyRisk(collectRenderPromptText(activeVideoSpec)),
    [activeVideoSpec],
  );
  const neutralizeRenderPrompt = useCallback(() => {
    setVideoSpec((prev) => neutralizeVideoSpecPolicyRisk(prev || activeVideoSpec));
    push({
      level: "info",
      title: "Prompt neutralized",
      message: "Removed real-person/likeness phrasing from explainer render inputs.",
      status: "succeeded",
      action: "article.video.render.neutralize",
      entityType: "unknown",
      entityId: artifactId,
    });
  }, [activeVideoSpec, artifactId, push]);
  const storyboardProposals = Array.isArray(activeVideoSpec.storyboard?.proposals) ? activeVideoSpec.storyboard.proposals : [];
  const videoScenes = Array.isArray(activeVideoSpec.scenes) ? activeVideoSpec.scenes : [];
  const sceneTitle = (scene: Record<string, unknown> | null | undefined, fallback: string) =>
    String(scene?.title ?? scene?.name ?? fallback).trim() || fallback;
  const sceneVoiceover = (scene: Record<string, unknown> | null | undefined) =>
    String(scene?.voiceover ?? scene?.narration ?? "").trim();
  const sceneOnScreen = (scene: Record<string, unknown> | null | undefined) =>
    String(scene?.on_screen ?? scene?.on_screen_text ?? "").trim();
  const selectedVideoScene =
    videoScenes.length > 0 ? videoScenes[Math.min(selectedVideoSceneIndex, videoScenes.length - 1)] : null;
  const selectedStoryboardScene =
    Array.isArray(activeVideoSpec.storyboard?.draft) && activeVideoSpec.storyboard.draft.length > 0
      ? activeVideoSpec.storyboard.draft[Math.min(selectedStoryboardSceneIndex, activeVideoSpec.storyboard.draft.length - 1)]
      : null;
  const scriptDraftText = String(activeVideoSpec.script?.draft || "").trim();
  const hasScriptDraft = scriptDraftText.length > 0;
  const hasScenes = videoScenes.length > 0;
  const storyboardDraftCount = Array.isArray(activeVideoSpec.storyboard?.draft) ? activeVideoSpec.storyboard.draft.length : 0;
  const hasStoryboardDraft = storyboardDraftCount > 0;
  const latestVideoRender = videoRenders[0] || null;
  const latestRenderIsStub = latestVideoRender?.provider === "unknown";
  const configuredForVideoRender =
    videoRenderingMode === "render_via_adapter" ||
    videoRenderingMode === "render_via_endpoint" ||
    videoRenderingMode === "render_via_model_config";
  const showProviderNotConfigured =
    !configuredForVideoRender &&
    (latestRenderIsStub || videoRenderingMode === "export_package_only" || !videoRenderingMode);
  const isVideoOperationRunning = videoBusy === "script" || videoBusy === "storyboard" || videoBusy === "render" || (latestVideoRender?.status === "queued" || latestVideoRender?.status === "running");
  const videoSummaryRows = [
    `Scenes: ${hasScenes ? `${videoScenes.length} scene${videoScenes.length === 1 ? "" : "s"}` : "not generated"}`,
    `Script view: ${hasScenes ? "derived from scenes" : hasScriptDraft ? "draft ready" : "not generated"}`,
    `Storyboard: ${hasStoryboardDraft ? `${storyboardDraftCount} scene${storyboardDraftCount === 1 ? "" : "s"}` : "not generated"}`,
    `Last render: ${latestVideoRender?.status || "none"}`,
  ];
  const selectedVideoContextPack = selectedVideoContextPackId ? videoContextPacks.find((pack) => pack.id === selectedVideoContextPackId) || null : null;
  const explainerRefinementContext = useMemo(() => {
    if (!isExplainerFormat) return "";
    const rows = [
      `Intent: ${activeVideoSpec.intent || "(none)"}`,
      `Audience: ${activeVideoSpec.audience || "(none)"}`,
      `Tone: ${activeVideoSpec.tone || "(none)"}`,
      `Duration target: ${activeVideoSpec.duration_seconds_target || "(none)"} seconds`,
    ];
    if (selectedVideoContextPack) {
      rows.push(`Context pack: ${selectedVideoContextPack.name} (v${selectedVideoContextPack.version})`);
    }
    return rows.join("\n");
  }, [activeVideoSpec.audience, activeVideoSpec.duration_seconds_target, activeVideoSpec.intent, activeVideoSpec.tone, isExplainerFormat, selectedVideoContextPack]);
  const missingConsoleFields = useMemo(
    () => new Set((consoleSession.pendingMissingFields || []).map((field) => field.field)),
    [consoleSession.pendingMissingFields]
  );

  const getFormSnapshot = useCallback(() => {
    return buildArticleDraftSnapshot({
      title,
      category,
      format: articleFormat,
      intent: activeVideoSpec.intent || "",
      duration: activeVideoSpec.duration_seconds_target || null,
      scenes: Array.isArray(activeVideoSpec.scenes) ? activeVideoSpec.scenes : [],
      tags: parseCsv(tagsText),
      summary,
      body: bodyMarkdown,
    }) as Record<string, unknown>;
  }, [activeVideoSpec.duration_seconds_target, activeVideoSpec.intent, articleFormat, bodyMarkdown, category, summary, tagsText, title]);

  const applyConsolePatchToForm = useCallback(
    (patch: Record<string, unknown>) => {
      const current = buildArticleDraftSnapshot({
        title,
        category,
        format: articleFormat,
        intent: activeVideoSpec.intent || "",
        duration: activeVideoSpec.duration_seconds_target || null,
        scenes: Array.isArray(activeVideoSpec.scenes) ? activeVideoSpec.scenes : [],
        tags: parseCsv(tagsText),
        summary,
        body: bodyMarkdown,
      });
      const result = applyPatchToFormSnapshot(current, patch || {});
      const next = result.next;
      if (next.title !== null) setTitle(next.title);
      if (next.category !== null) setCategory(next.category);
      if (next.format && next.format !== articleFormat) {
        setArticleFormat(next.format as ArticleFormat);
        if (next.format === "video_explainer") {
          void ensureVideoInitialized();
        }
      }
      setSummary(next.summary || "");
      setBodyMarkdown(next.body || "");
      setTagsText((next.tags || []).join(", "));
      setVideoSpec((prev) => {
        const base = prev || createDefaultVideoSpec(next.title || title, next.summary || "");
        const mappedScenes =
          Array.isArray(next.scenes) && next.scenes.length > 0
            ? next.scenes.map((scene, index) => {
                const row = scene as Record<string, unknown>;
                const id = String(row.id || `s${index + 1}`).trim() || `s${index + 1}`;
                const name = String(row.name || row.title || `Scene ${index + 1}`).trim() || `Scene ${index + 1}`;
                const narration = String(row.narration || row.voiceover || "").trim();
                const onScreen = String(row.on_screen_text || row.on_screen || "").trim();
                const visualPrompt = String(row.visual_prompt || row.visual_description || name).trim();
                return {
                  id,
                  name,
                  duration_seconds: Number(row.duration_seconds) || 8,
                  narration,
                  visual_prompt: visualPrompt,
                  on_screen_text: onScreen,
                  camera_motion: String(row.camera_motion || "").trim(),
                  style_constraints: Array.isArray(row.style_constraints)
                    ? row.style_constraints.map((value) => String(value || "").trim()).filter(Boolean)
                    : [],
                  generated: row.generated && typeof row.generated === "object"
                    ? (row.generated as { image_asset_url?: string | null; video_clip_url?: string | null })
                    : { image_asset_url: null, video_clip_url: null },
                };
              })
            : base.scenes || [];
        return {
          ...base,
          intent: next.intent || base.intent || "",
          duration_seconds_target: next.duration || base.duration_seconds_target || 150,
          scenes: mappedScenes,
        };
      });
      return {
        appliedFields: result.appliedFields,
        ignoredFields: result.ignoredFields,
      };
    },
    [activeVideoSpec.duration_seconds_target, activeVideoSpec.intent, activeVideoSpec.scenes, articleFormat, bodyMarkdown, category, ensureVideoInitialized, parseCsv, summary, tagsText, title]
  );

  const focusConsoleField = useCallback(
    (field: string): boolean => {
      if (field === "title") {
        titleFieldRef.current?.focus();
        titleFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      }
      if (field === "format") {
        formatFieldRef.current?.focus();
        formatFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      }
      if (field === "category") {
        const target = categorySelectFieldRef.current || categoryInputFieldRef.current;
        target?.focus();
        target?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      }
      if (field === "tags") {
        tagsFieldRef.current?.focus();
        tagsFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      }
      if (field === "summary") {
        summaryFieldRef.current?.focus();
        summaryFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        return true;
      }
      if (field === "intent") {
        setArticleFormat("video_explainer");
        setVideoTab("scenes");
        setVideoPanelCollapsed(false);
        window.setTimeout(() => {
          videoIntentFieldRef.current?.focus();
          videoIntentFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 0);
        return true;
      }
      if (field === "duration") {
        setArticleFormat("video_explainer");
        setVideoTab("scenes");
        setVideoPanelCollapsed(false);
        window.setTimeout(() => {
          videoDurationFieldRef.current?.focus();
          videoDurationFieldRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 0);
        return true;
      }
      if (field === "body") {
        setShowPreview(false);
        setEditorFocusSignal((current) => current + 1);
        return true;
      }
      return false;
    },
    []
  );

  const applyConsoleFieldValue = useCallback(
    (field: string, value: unknown): boolean => {
      if (field === "category") {
        const next = String(value || "").trim();
        if (!next) return false;
        setCategory(next);
        return true;
      }
      if (field === "format") {
        const next = String(value || "").trim() as ArticleFormat;
        if (!next) return false;
        setArticleFormat(next);
        if (next === "video_explainer") {
          void ensureVideoInitialized();
        }
        return true;
      }
      if (field === "duration") {
        const numeric = Number(value);
        if (!Number.isFinite(numeric) || numeric <= 0) return false;
        setArticleFormat("video_explainer");
        setVideoSpec((prev) => {
          const base = prev || createDefaultVideoSpec(title, summary);
          return {
            ...base,
            duration_seconds_target: Math.round(numeric),
          };
        });
        return true;
      }
      return false;
    },
    [ensureVideoInitialized, summary, title]
  );

  useEffect(() => {
    if (!artifactId) return;
    registerEditorBridge(
      { artifact_id: artifactId, artifact_type: "ArticleDraft" },
      {
        getFormSnapshot,
        applyPatchToForm: applyConsolePatchToForm,
        focusField: focusConsoleField,
        applyFieldValue: applyConsoleFieldValue,
      }
    );
    return () => {
      unregisterEditorBridge({ artifact_id: artifactId, artifact_type: "ArticleDraft" });
    };
  }, [artifactId, applyConsoleFieldValue, applyConsolePatchToForm, focusConsoleField, getFormSnapshot, registerEditorBridge, unregisterEditorBridge]);
  const refinementAnchorStyle = useMemo(() => {
    if (!refinementAnchorRect) return undefined;
    const top = Math.max(16, refinementAnchorRect.top + refinementAnchorRect.height + 10);
    const left = Math.max(12, refinementAnchorRect.left);
    return {
      position: "fixed" as const,
      top,
      left,
    };
  }, [refinementAnchorRect]);
  const isMobileRefinement =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(max-width: 960px)").matches
      : false;
  const refinementSelection =
    refinementSurface === "script" ? scriptSelection : refinementSurface === "storyboard" ? storyboardSelection : editorSelection;
  const refinementSelectedText = refinementSelection?.selectedText || null;
  const refinementVideoContext = isExplainerFormat
    ? {
        intent: activeVideoSpec.intent || "",
        audience: activeVideoSpec.audience || "",
        tone: activeVideoSpec.tone || "",
        duration: activeVideoSpec.duration_seconds_target || null,
      }
    : null;

  const collapsedPrimaryAction = useMemo(() => {
    if (!hasScenes) {
      return {
        label: "Regenerate scenes…",
        disabled: Boolean(videoBusy),
        run: openRegenerateScenesPreview,
      };
    }
    if (!hasStoryboardDraft) {
      return {
        label: videoBusy === "storyboard" ? "Generating storyboard…" : "Generate storyboard",
        disabled: Boolean(videoBusy),
        run: () => void generateVideoStoryboardDraft(),
      };
    }
    return {
      label: videoBusy === "render" ? "Queueing render…" : "Render",
      disabled: Boolean(videoBusy),
      run: () => void requestVideoRender(),
    };
  }, [generateVideoStoryboardDraft, hasScenes, hasStoryboardDraft, openRegenerateScenesPreview, requestVideoRender, videoBusy]);

  const videoPanelStorageKey = artifactId ? `xyn.videoPanelCollapsed:${artifactId}` : "";

  useEffect(() => {
    if (!videoPanelStorageKey || articleFormat !== "video_explainer") return;
    const stored = localStorage.getItem(videoPanelStorageKey);
    if (stored === "true" || stored === "false") {
      setVideoPanelCollapsed(stored === "true");
      return;
    }
    setVideoPanelCollapsed(false);
  }, [articleFormat, videoPanelStorageKey]);

  useEffect(() => {
    if (!videoPanelStorageKey || articleFormat !== "video_explainer") return;
    localStorage.setItem(videoPanelStorageKey, videoPanelCollapsed ? "true" : "false");
  }, [articleFormat, videoPanelCollapsed, videoPanelStorageKey]);

  const toggleVideoPanelCollapsed = useCallback(() => {
    setVideoPanelCollapsed((current) => {
      const next = !current;
      if (current) {
        requestAnimationFrame(() => {
          videoPanelRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
        });
      }
      return next;
    });
  }, []);

  const openRefinement = useCallback(
    (surface: RefinementSurface, anchor?: EditorSelection["anchorRect"] | null) => {
      setRefinementSurface(surface);
      setRefinementAnchorRect(anchor || null);
      setRefinementOpen(true);
    },
    []
  );

  const applySurfaceRefinement = useCallback(() => {
    if (!pendingSurfaceRefinement) return;
    if (pendingSurfaceRefinement.surface === "script") {
      setVideoSpec({
        ...activeVideoSpec,
        script: {
          ...(activeVideoSpec.script || { draft: "", proposals: [] }),
          draft: pendingSurfaceRefinement.nextText,
        },
      });
      setVideoTab("script");
    }
    if (pendingSurfaceRefinement.surface === "storyboard") {
      const sceneIndex = pendingSurfaceRefinement.storyboardSceneIndex ?? -1;
      const field = pendingSurfaceRefinement.storyboardField;
      if (sceneIndex >= 0 && field) {
        const nextDraft = [...(activeVideoSpec.storyboard?.draft || [])];
        const scene = nextDraft[sceneIndex];
        if (scene) {
          nextDraft[sceneIndex] = { ...scene, [field]: pendingSurfaceRefinement.nextText };
          setVideoSpec({
            ...activeVideoSpec,
            storyboard: {
              ...(activeVideoSpec.storyboard || { draft: [] }),
              draft: nextDraft,
            },
          });
          setSelectedStoryboardSceneIndex(sceneIndex);
          setVideoTab("storyboard");
        }
      }
    }
    setPendingSurfaceRefinement(null);
  }, [activeVideoSpec, pendingSurfaceRefinement]);

  useEffect(() => {
    const onKeydown = (event: KeyboardEvent) => {
      const isShortcut = (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k";
      if (!isShortcut || !canRefineSelection) return;
      event.preventDefault();
      openRefinement(selectionSurface || "article", activeSelection?.anchorRect || null);
    };
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [activeSelection?.anchorRect, canRefineSelection, openRefinement, selectionSurface]);

  const executeAction = async (action: WorkflowAction) => {
    try {
      setBusyActionId(action.id);
      setError(null);
      switch (action.id) {
        case "save_revision":
          await save();
          break;
        case "mark_reviewed":
          await transition("reviewed");
          break;
        case "mark_ratified":
          await transition("ratified");
          break;
        case "publish":
          await transition("published");
          break;
        case "deprecate":
          await transition("deprecated");
          break;
        case "endorse":
          await react("endorse");
          break;
        case "oppose":
          await react("oppose");
          break;
        case "neutral":
          await react("neutral");
          break;
        case "view_revisions":
          setActivityTab("revisions");
          setRevisionMode("list");
          if (revisions.length === 0) {
            push({
              title: "Revision history",
              message: "No revisions yet. Save a revision to populate history.",
              level: "info",
            });
          } else {
            push({
              title: "Revision history",
              message: `Showing ${revisions.length} revision${revisions.length === 1 ? "" : "s"}.`,
              level: "info",
            });
          }
          break;
        default:
          break;
      }
    } finally {
      setBusyActionId(null);
    }
  };

  const handleAction = async (action: WorkflowAction) => {
    if (!action.enabled) return;
    if (action.confirmation) {
      setConfirmingAction(action);
      return;
    }
    await executeAction(action);
  };

  const resolvePublishedUrl = (entry: NonNullable<ArticleDetail["published_to"]>[number]) => {
    if (!item) return "";
    const value = String(entry.target_value || "").trim();
    if (!value) return "";
    const slug = encodeURIComponent(String(item.slug || "").trim());
    const appendSlug = (base: string) => {
      if (!slug) return base;
      const normalized = base.replace(/\/+$/, "");
      if (normalized.endsWith(`/${slug}`)) return normalized;
      return `${normalized}/${slug}`;
    };
    if (entry.target_type === "external_url") return appendSlug(value);
    if (!origin) return value;
    if (entry.target_type === "public_web_path") {
      const base = `${origin}${value.startsWith("/") ? value : `/${value}`}`;
      return appendSlug(base);
    }
    const routeBase = `${origin}${value.startsWith("/") ? value : `/${value}`}`;
    if (value.startsWith("/app/")) return routeBase;
    return appendSlug(routeBase);
  };

  const revisionPanel = (
    <div className="stack revision-panel">
      <div className="card-header">
        <h3>Revision History</h3>
      </div>
      <div className="instance-list revision-list">
        {revisions.map((rev) => (
          <div className={`instance-row revision-row ${selectedRevision?.id === rev.id ? "active" : ""}`} key={rev.id}>
            <div className="revision-meta">
              <div className="revision-meta-top">
                <strong>r{rev.revision_number}</strong>
                <span className="muted small">
                  {rev.created_at || "—"}
                  {rev.created_by_email ? ` · ${rev.created_by_email}` : ""}
                </span>
              </div>
            </div>
            <div className="inline-actions revision-actions">
              <div className="revision-actions-main">
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => {
                    setSelectedRevisionId(rev.id);
                    setRevisionMode("view");
                  }}
                >
                  View
                </button>
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => {
                    setSelectedRevisionId(rev.id);
                    setCompareRevisionId("current");
                    setRevisionMode("diff");
                  }}
                >
                  Diff current
                </button>
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => {
                    setSelectedRevisionId(rev.id);
                    setRevisionMode("diff");
                  }}
                >
                  Compare
                </button>
              </div>
              <button className="danger sm revision-restore-button" type="button" onClick={() => setRestoreRevisionId(rev.id)}>
                Restore
              </button>
            </div>
          </div>
        ))}
        {revisions.length === 0 && <p className="muted">No revisions yet.</p>}
      </div>
    </div>
  );

  const aiConfigDirty =
    JSON.stringify(videoAiConfigDraft?.agents || {}) !== JSON.stringify(videoAiConfigOverrides?.agents || {}) ||
    JSON.stringify(videoAiConfigDraft?.context_packs || {}) !== JSON.stringify(videoAiConfigOverrides?.context_packs || {});

  const aiConfigPanel = (
    <div className="stack activity-ai-config-panel">
      <div className="card-header">
        <h3>AI Configuration</h3>
      </div>
      <p className="muted small">Agent is the primary control. Context packs are optional per-step overrides under Advanced.</p>
      {EXPLAINER_PURPOSE_META.map((purpose) => {
        const effective = videoAiConfigEffective[purpose.slug];
        const agentOptions = videoPurposeAgents[purpose.slug] || [];
        const packOptions = videoPurposeContextPacks[purpose.slug] || [];
        const hasAgentOverride = Boolean(videoAiConfigDraft.agents?.[purpose.slug]);
        const hasPackOverride = Boolean(videoAiConfigDraft.context_packs?.[purpose.slug]);
        const selectedPackIds = readOverridePackIds(purpose.slug);
        const overrideMode = readOverrideMode(purpose.slug);
        const effectiveRefs = effective?.effective_context_pack_refs || [];
        return (
          <section className="ai-config-row" key={purpose.slug}>
            <div className="card-header">
              <h4>{purpose.name}</h4>
              <span className={`ai-config-indicator ${(hasAgentOverride || hasPackOverride) ? "override" : "default"}`}>
                {(hasAgentOverride || hasPackOverride) ? <Pencil size={12} aria-label="Override configured" /> : <Lock size={12} aria-label="Using defaults" />}
              </span>
            </div>
            <p className="muted small">{purpose.description}</p>
            <label>
              Agent
              <select value={videoAiConfigDraft.agents?.[purpose.slug] || ""} onChange={(event) => setOverrideAgent(purpose.slug, event.target.value)}>
                <option value="">Use Default</option>
                {agentOptions.map((agent) => (
                  <option key={agent.id} value={agent.slug}>
                    {agent.name} ({agent.slug}) · {agent.model_config?.provider}/{agent.model_config?.model_name}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted small">
              Effective agent: {effective?.agent?.name || "None"} · Model: {effective?.agent?.model_provider || "—"}/{effective?.agent?.model_name || "—"} ·
              Packs: {effective?.context_packs?.length || 0}
              {effective?.warning ? ` · ${effective.warning}` : ""}
            </p>
            {effectiveRefs.length > 0 && (
              <p className="muted small">
                {effectiveRefs.map((entry) => `${entry.name} v${entry.version || "?"} (${entry.source || "resolved"})`).join(" · ")}
              </p>
            )}
            <details className="ai-config-advanced">
              <summary>Advanced overrides</summary>
              <label>
                Override mode
                <select value={overrideMode} onChange={(event) => setOverrideContextMode(purpose.slug, event.target.value as "extend" | "replace")}>
                  <option value="extend">Extend agent defaults</option>
                  <option value="replace">Replace agent defaults</option>
                </select>
              </label>
              <label>
                Additional context packs (optional)
                <select
                  multiple
                  size={Math.min(4, Math.max(2, packOptions.length || 2))}
                  value={selectedPackIds}
                  onChange={(event) => {
                    const ids = Array.from(event.target.selectedOptions).map((entry) => entry.value).filter(Boolean);
                    setOverrideContextPacks(purpose.slug, ids);
                  }}
                >
                  {packOptions.map((pack) => (
                    <option key={pack.id} value={pack.id}>
                      {pack.name} · v{pack.version}
                    </option>
                  ))}
                </select>
                <button className="ghost sm" type="button" onClick={() => setOverrideContextPacks(purpose.slug, [])}>
                  Clear overrides
                </button>
              </label>
            </details>
          </section>
        );
      })}
      <div className="inline-actions">
        <button className="primary sm" type="button" onClick={() => void saveVideoAiConfig()} disabled={videoAiConfigBusy || !aiConfigDirty}>
          {videoAiConfigBusy ? "Saving…" : "Save"}
        </button>
        <button className="ghost sm" type="button" onClick={() => void resetVideoAiConfig()} disabled={videoAiConfigBusy}>
          Reset all to defaults
        </button>
      </div>
    </div>
  );

  const discussionPanel = (
    <div className="stack">
      <div className="card-header">
        <h3>Reactions & Comments</h3>
      </div>
      <p className="muted">
        endorse: {item?.reactions?.endorse || 0} | oppose: {item?.reactions?.oppose || 0} | neutral: {item?.reactions?.neutral || 0}
      </p>
      <label>
        Add comment
        <textarea className="input" rows={3} value={commentBody} onChange={(event) => setCommentBody(event.target.value)} />
      </label>
      <button className="primary" type="button" onClick={addComment} disabled={!commentBody.trim()}>
        Reply
      </button>
      <div className="instance-list">
        {(item?.comments || []).map((comment) => (
          <div className="instance-row" key={comment.id}>
            <div>
              <strong>{comment.status}</strong>
              <span className="muted small">{comment.body}</span>
            </div>
            {(workspaceRole === "moderator" || workspaceRole === "admin") && (
              <div className="inline-actions">
                <button className="ghost" type="button" onClick={() => void moderate(comment.id, "hidden")}>
                  Hide
                </button>
                <button className="danger" type="button" onClick={() => void moderate(comment.id, "deleted")}>
                  Delete
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );

  const credibilityPanel = (
    <ArtifactCredibilityLayer
      artifactId={artifactId}
      artifactType="article"
      titleFallback={item?.title || "Artifact"}
      showIntentScriptAction={articleFormat !== "video_explainer"}
      onGoToBody={() => {
        setEditorFocusSignal((prev) => prev + 1);
        window.requestAnimationFrame(() => {
          const editor = document.querySelector(".editor-body");
          if (editor instanceof HTMLElement) {
            editor.scrollIntoView({ behavior: "smooth", block: "center" });
          }
        });
      }}
    />
  );

  const activityPanel = (
    <div className="stack">
      <CompactPaneTabs
        ariaLabel="Activity panel tabs"
        activeKey={activityTab}
        onChange={(next) => setActivityTab(next as ActivityTab)}
        tabs={
          [
            { key: "overview", label: "Overview", icon: <Sparkles size={15} /> },
            { key: "revisions", label: "Revisions", icon: <History size={15} /> },
            { key: "surfaces", label: "Surfaces", icon: <SlidersHorizontal size={15} /> },
            ...(canDebugRaw ? [{ key: "raw", label: "Raw / Files", icon: <SlidersHorizontal size={15} /> }] : []),
            ...(articleFormat === "video_explainer"
              ? [{ key: "ai_config", label: "AI Configuration", icon: <SlidersHorizontal size={15} /> }]
              : []),
            {
              key: "discussion",
              label: "Reactions & Comments",
              icon: <MessageSquareMore size={15} />,
              badgeCount: (item?.comments?.length || 0) + ((item?.reactions?.endorse || 0) + (item?.reactions?.oppose || 0) + (item?.reactions?.neutral || 0)),
            },
          ] satisfies CompactPaneTab[]
        }
      />
      {activityTab === "overview" && credibilityPanel}
      {activityTab === "revisions" && revisionPanel}
      {activityTab === "surfaces" && (
        <div className="card stack">
          <div className="stack">
            <strong>Artifact Surfaces</strong>
            {(artifactSurfaces || []).length === 0 ? (
              <span className="muted small">No surfaces declared for this artifact.</span>
            ) : (
              <div className="instance-list">
                {artifactSurfaces.map((surface) => (
                  <div className="instance-row" key={surface.id}>
                    <div className="stack">
                      <strong>{surface.title || surface.key}</strong>
                      <span className="muted small">
                        {surface.surface_kind} · {surface.route} · {surface.nav_visibility}
                      </span>
                      <span className="muted small">
                        renderer: {String((surface.renderer?.type as string) || "unknown")}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
          <div className="stack">
            <strong>Runtime Roles</strong>
            {(artifactRuntimeRoles || []).length === 0 ? (
              <span className="muted small">No runtime roles declared for this artifact.</span>
            ) : (
              <div className="instance-list">
                {artifactRuntimeRoles.map((role) => (
                  <div className="instance-row" key={role.id}>
                    <div className="stack">
                      <strong>{role.role_kind}</strong>
                      <span className="muted small">enabled: {role.enabled ? "yes" : "no"}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
      {activityTab === "raw" && (
        <div className="card stack">
          {!rawAccessKnown ? <p className="muted small">Checking permissions…</p> : null}
          {rawAccessKnown && !canDebugRaw ? (
            <p className="muted small">
              Raw artifact view requires <code>artifact_debug_view</code> (or platform admin/architect role).
            </p>
          ) : null}
          {canDebugRaw ? (
            <>
              <div className="inline-actions">
                <button className="ghost sm" type="button" onClick={() => void loadRawArtifactView()} disabled={rawLoading}>
                  Refresh
                </button>
                {artifactId ? (
                  <a className="ghost sm" href={getArtifactRawFileDownloadUrl(artifactId, "/artifact.json")} target="_blank" rel="noreferrer">
                    Download artifact.json
                  </a>
                ) : null}
              </div>
              {rawError ? <p className="error-message">{rawError}</p> : null}
              <div className="split">
                <div className="card stack">
                  <strong>Path {rawPath}</strong>
                  {rawPath !== "/" && artifactId ? (
                    <button
                      className="ghost sm"
                      type="button"
                      onClick={async () => {
                        const parent = rawPath === "/" ? "/" : rawPath.split("/").slice(0, -1).join("/") || "/";
                        const next = await listArtifactRawFiles(artifactId, parent);
                        setRawEntries(next.entries || []);
                        setRawPath(next.path || "/");
                      }}
                    >
                      Up one level
                    </button>
                  ) : null}
                  <div className="instance-list">
                    <button
                      className="instance-row"
                      type="button"
                      onClick={() => {
                        setRawSelectedPath("/artifact.json");
                        setRawPreview({ inline: true, content: JSON.stringify(rawArtifactJson || {}, null, 2), path: "/artifact.json" });
                      }}
                    >
                      /artifact.json
                    </button>
                    {rawEntries.map((entry) => (
                      <button
                        key={entry.path}
                        className="instance-row"
                        type="button"
                        onClick={() => void openRawPath(entry)}
                      >
                        <span>
                          [{entry.kind === "dir" ? "dir" : "file"}] {entry.path}
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
                <div className="card stack">
                  <strong>Raw metadata</strong>
                  {rawMeta ? <pre className="code-block">{JSON.stringify(rawMeta, null, 2)}</pre> : <p className="muted small">No metadata loaded.</p>}
                  <strong>File preview: {rawSelectedPath}</strong>
                  {rawPreview ? (
                    "content" in rawPreview ? (
                      <pre className="code-block">{String((rawPreview as Record<string, unknown>).content || "")}</pre>
                    ) : (
                      <div className="inline-actions">
                        <span className="muted small">Binary or large file. Download to inspect.</span>
                        {artifactId ? (
                          <a
                            className="ghost sm"
                            href={getArtifactRawFileDownloadUrl(artifactId, rawSelectedPath)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Download
                          </a>
                        ) : null}
                      </div>
                    )
                  ) : (
                    <p className="muted small">Select a file to preview.</p>
                  )}
                </div>
              </div>
            </>
          ) : null}
        </div>
      )}
      {activityTab === "ai_config" && articleFormat === "video_explainer" && aiConfigPanel}
      {activityTab === "discussion" && discussionPanel}
    </div>
  );

  const inspectorPanel = (
    <div className="stack">
      <div className="card-header">
        <h3>Inspector</h3>
      </div>
      <div className="field-group">
        <label className="field-label" htmlFor="article-title">
          Title
        </label>
        <input
          id="article-title"
          ref={titleFieldRef}
          className={`input ${missingConsoleFields.has("title") ? "console-missing-field" : ""}`}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </div>
      <div className="field-group">
        <label className="field-label" htmlFor="article-format">
          Format
        </label>
        <select
          id="article-format"
          ref={formatFieldRef}
          className={missingConsoleFields.has("format") ? "console-missing-field" : ""}
          value={articleFormat}
          onChange={(event) => {
            const next = event.target.value as ArticleFormat;
            setArticleFormat(next);
            if (next === "video_explainer") {
              void ensureVideoInitialized();
            }
          }}
        >
          <option value="standard">Standard Article</option>
          <option value="video_explainer">Explainer Video</option>
        </select>
      </div>
      <div className="field-group">
        <label className="field-label" htmlFor="article-category">
          Category
        </label>
        {isDeprecatedCategory ? (
          <div className="stacked-field">
            <input
              id="article-category"
              ref={categoryInputFieldRef}
              className={`input ${missingConsoleFields.has("category") ? "console-missing-field" : ""}`}
              value={`${selectedCategoryMeta?.name || category} (${category})`}
              disabled
            />
            <span className="muted small">Deprecated category (read-only)</span>
          </div>
        ) : (
          <select
            id="article-category"
            ref={categorySelectFieldRef}
            className={missingConsoleFields.has("category") ? "console-missing-field" : ""}
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            {categoryOptions.length === 0 && (
              <>
                <option value="web">web</option>
                <option value="guide">guide</option>
                <option value="core-concepts">core-concepts</option>
              </>
            )}
            {selectableCategoryOptions.map((entry) => (
              <option key={entry.slug} value={entry.slug}>
                {entry.name} ({entry.slug})
              </option>
            ))}
          </select>
        )}
      </div>
      <div className="field-group">
        <label className="field-label" htmlFor="article-visibility">
          Visibility
        </label>
        <select id="article-visibility" value={visibilityType} onChange={(event) => setVisibilityType(event.target.value as typeof visibilityType)}>
          <option value="public">public</option>
          <option value="authenticated">authenticated</option>
          <option value="role_based">role_based</option>
          <option value="private">private</option>
        </select>
      </div>
      {visibilityType === "role_based" && (
        <div className="field-group">
          <label className="field-label" htmlFor="article-allowed-roles">
            Allowed roles (comma-separated)
          </label>
          <input id="article-allowed-roles" className="input" value={allowedRolesText} onChange={(event) => setAllowedRolesText(event.target.value)} />
        </div>
      )}
      <div className="field-group">
        <label className="field-label" htmlFor="article-tags">
          Tags (comma-separated)
        </label>
        <input
          id="article-tags"
          ref={tagsFieldRef}
          className={`input ${missingConsoleFields.has("tags") ? "console-missing-field" : ""}`}
          value={tagsText}
          onChange={(event) => setTagsText(event.target.value)}
        />
      </div>
      <div className="field-group">
        <label className="field-label" htmlFor="article-summary">
          Summary
        </label>
        <textarea
          id="article-summary"
          ref={summaryFieldRef}
          className={`input field-textarea ${missingConsoleFields.has("summary") ? "console-missing-field" : ""}`}
          rows={4}
          value={summary}
          onChange={(event) => setSummary(event.target.value)}
        />
        <div className="summary-ai-action-row">
          <button
            className="ghost sm subtle-action"
            type="button"
            onClick={() => void summarizeWithAi()}
            disabled={summaryBusy || assistBusy || !selectedAgent || !bodyMarkdown.trim()}
            title={selectedAgent ? "Generate and replace summary using the selected refinement agent." : "Select a refinement agent with Refine first."}
          >
            {summaryBusy ? "Summarizing…" : "AI Summarize"}
          </button>
        </div>
      </div>
      {articleFormat === "video_explainer" && (
        <div className="stack explainer-inspector-settings">
          <div className="card-header">
            <h4>Explainer Settings</h4>
          </div>
          <div className="field-group">
            <label className="field-label">Context pack</label>
            <select
              className="input"
              value={selectedVideoContextPackId}
              onChange={(event) => setSelectedVideoContextPackId(event.target.value)}
            >
              <option value="">None</option>
              {videoContextPacks.map((pack) => (
                <option key={pack.id} value={pack.id}>
                  {pack.name} · v{pack.version}
                </option>
              ))}
            </select>
          </div>
          <div className="field-group">
            <label className="field-label" htmlFor="article-intent">Intent</label>
            <textarea
              id="article-intent"
              rows={3}
              ref={videoIntentFieldRef}
              className={`input ${missingConsoleFields.has("intent") ? "console-missing-field" : ""}`}
              value={activeVideoSpec.intent || ""}
              onChange={(event) => setVideoSpec({ ...activeVideoSpec, intent: event.target.value })}
            />
          </div>
          <div className="field-group">
            <label className="field-label">Audience</label>
            <input
              className="input"
              value={activeVideoSpec.audience || ""}
              onChange={(event) => setVideoSpec({ ...activeVideoSpec, audience: event.target.value })}
            />
          </div>
          <div className="field-group">
            <label className="field-label">Tone</label>
            <input className="input" value={activeVideoSpec.tone || ""} onChange={(event) => setVideoSpec({ ...activeVideoSpec, tone: event.target.value })} />
          </div>
          <div className="field-group">
            <label className="field-label" htmlFor="article-duration">Duration target (seconds)</label>
            <input
              id="article-duration"
              ref={videoDurationFieldRef}
              className={`input ${missingConsoleFields.has("duration") ? "console-missing-field" : ""}`}
              type="number"
              min={10}
              value={activeVideoSpec.duration_seconds_target || 150}
              onChange={(event) =>
                setVideoSpec({ ...activeVideoSpec, duration_seconds_target: Number(event.target.value) || activeVideoSpec.duration_seconds_target })
              }
            />
          </div>
          <button className="ghost sm" type="button" onClick={() => void persistVideoSpec(activeVideoSpec)} disabled={videoBusy === "save"}>
            {videoBusy === "save" ? "Saving…" : "Save explainer settings"}
          </button>
        </div>
      )}
      <div className="inline-actions">
        <button className="primary" type="button" onClick={() => void save()}>
          Save revision
        </button>
        {articleFormat === "video_explainer" && (
          <a className="ghost" href={`/xyn/api/articles/${artifactId}/video/export-package`} target="_blank" rel="noreferrer noopener">
            Export package
          </a>
        )}
        {!bodyMarkdown.trim() && legacyBodyHtml.trim() && (
          <button className="ghost" type="button" onClick={() => void convertLegacyHtml()}>
            Convert HTML to Markdown
          </button>
        )}
      </div>
      <div className="card-header">
        <h4>Published to</h4>
      </div>
      <div className="instance-list">
        {(item?.published_to || []).map((entry) => {
          const url = resolvePublishedUrl(entry);
          return (
            <div className="instance-row" key={`${entry.source}-${entry.target_type}-${entry.target_value}`}>
              <div>
                <strong>{entry.label}</strong>
                <span className="muted small">
                  {entry.target_type} · {entry.target_value} · {entry.source === "category" ? "Inherited (Category)" : "Article-specific"}
                </span>
                {url && (
                  <a className="muted small" href={url} target="_blank" rel="noreferrer noopener" style={{ display: "block", marginTop: 4 }}>
                    {url}
                  </a>
                )}
              </div>
            </div>
          );
        })}
        {(item?.published_to || []).length === 0 && <p className="muted">No publish bindings resolved.</p>}
      </div>
    </div>
  );

  const topSection = (
    <div className="stack artifact-editor-top-section">
      <section className="artifact-draft-bar">
        <div className="artifact-draft-bar-main">
          <input className="input artifact-draft-bar-title" value={title} onChange={(event) => setTitle(event.target.value)} aria-label="Draft title" />
          <span className={`status-pill status-${workflow.statusTone}`}>{workflow.statusLabel}</span>
          <span className="muted small">{workflow.nextStepLabel}</span>
          {workflow.blockers.length > 0 && <span className="muted small">Blocking: {workflow.blockers[0]}</span>}
        </div>
        <div className="inline-actions">
          <button className="primary sm" type="button" onClick={() => void save()}>
            Save
          </button>
          {workflow.primaryAction && (
            <button
              className={workflow.primaryAction.intent === "danger" ? "danger sm" : "primary sm"}
              type="button"
              onClick={() => handleAction(workflow.primaryAction as WorkflowAction)}
              disabled={!workflow.primaryAction.enabled || busyActionId === workflow.primaryAction.id}
              title={workflow.primaryAction.disabledReason || undefined}
            >
              {workflow.primaryAction.label}
            </button>
          )}
          <div className="artifact-workflow-actions-menu">
            <button
              className="ghost sm"
              type="button"
              onClick={() => setDraftBarActionsOpen((current) => !current)}
              aria-haspopup="menu"
              aria-expanded={draftBarActionsOpen}
            >
              Actions
            </button>
            <Popover open={draftBarActionsOpen} onClose={() => setDraftBarActionsOpen(false)} className="artifact-workflow-popover">
              <div className="artifact-workflow-menu" role="menu" aria-label="Artifact actions">
                {draftBarActionGroups.length === 0 ? (
                  <div className="xyn-menu-item disabled" role="status" aria-live="polite">
                    <span>No additional actions</span>
                  </div>
                ) : (
                  draftBarActionGroups.map((entry) => (
                    <div key={entry.group} className={`artifact-workflow-menu-group ${entry.group === "position" ? "is-reactions" : ""}`}>
                      <div className="artifact-workflow-menu-group-label">{entry.label}</div>
                      {entry.actions.map((action) => (
                        <button
                          key={action.id}
                          type="button"
                          role="menuitem"
                          className={`xyn-menu-item ${!action.enabled ? "disabled" : ""}`}
                          disabled={!action.enabled || busyActionId === action.id}
                          title={action.disabledReason || undefined}
                          onClick={() => {
                            handleAction(action);
                            setDraftBarActionsOpen(false);
                          }}
                        >
                          <span>{action.label}</span>
                          {!action.enabled && action.disabledReason && (
                            <span className="muted small artifact-workflow-action-reason">{action.disabledReason}</span>
                          )}
                        </button>
                      ))}
                    </div>
                  ))
                )}
              </div>
            </Popover>
          </div>
        </div>
      </section>
    </div>
  );

  const videoEditorPanel =
    articleFormat === "video_explainer" ? (
      <section ref={videoPanelRef} className={`card video-explainer-panel ${videoPanelCollapsed ? "collapsed" : "expanded"}`}>
        <div className="card-header">
          <h4>Explainer Video</h4>
          <div className="inline-actions">
            {!videoPanelCollapsed && (
              <>
                <button className={`ghost sm ${videoTab === "scenes" ? "active" : ""}`} type="button" onClick={() => setVideoTab("scenes")}>
                  Scenes
                </button>
                <button className={`ghost sm ${videoTab === "script" ? "active" : ""}`} type="button" onClick={() => setVideoTab("script")}>
                  Script
                </button>
                <button className={`ghost sm ${videoTab === "storyboard" ? "active" : ""}`} type="button" onClick={() => setVideoTab("storyboard")}>
                  Storyboard
                </button>
                <button className={`ghost sm ${videoTab === "renders" ? "active" : ""}`} type="button" onClick={() => setVideoTab("renders")}>
                  Render
                </button>
              </>
            )}
            <button
              className="ghost sm"
              type="button"
              aria-label={videoPanelCollapsed ? "Expand explainer panel" : "Collapse explainer panel"}
              title={videoPanelCollapsed ? "Expand" : "Collapse"}
              onClick={toggleVideoPanelCollapsed}
            >
              {videoPanelCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
            </button>
          </div>
        </div>
        {videoPanelCollapsed ? (
          <div className="video-panel-summary">
            <p className="muted small">Generated outputs are provisional. Accept or refine.</p>
            <p className="muted small">Scenes are scaffolded from title/topic at draft creation.</p>
            <div className="video-panel-summary-grid">
              {videoSummaryRows.map((row) => (
                <span key={row} className="muted small">
                  {row}
                </span>
              ))}
            </div>
            <div className="inline-actions">
              <button className="primary sm" type="button" onClick={collapsedPrimaryAction.run} disabled={collapsedPrimaryAction.disabled}>
                {collapsedPrimaryAction.label}
              </button>
              <button className="ghost sm" type="button" onClick={() => setVideoTab("renders")} disabled={Boolean(videoBusy)}>
                Open Render
              </button>
              <button className="ghost sm" type="button" onClick={toggleVideoPanelCollapsed} aria-label="Expand explainer panel">
                Expand
              </button>
            </div>
            {isVideoOperationRunning && <span className="muted small">Processing…</span>}
          </div>
        ) : (
          <>
            <p className="muted small">Generated outputs are provisional. Accept or refine.</p>
            <p className="muted small">Scenes are scaffolded from title/topic at draft creation.</p>
            {videoTab === "scenes" && (
          <div className="editor-body split">
            <div className="instance-list">
              {videoScenes.map((scene, index) => (
                <button
                  type="button"
                  key={`${scene.id || scene.title || scene.name}-${index}`}
                  className={`instance-row ${selectedVideoSceneIndex === index ? "active" : ""}`}
                  onClick={() => setSelectedVideoSceneIndex(index)}
                >
                  <div>
                    <strong>{sceneTitle(scene as unknown as Record<string, unknown>, `Scene ${index + 1}`)}</strong>
                    <span className="muted small">{scene.id || `s${index + 1}`}</span>
                  </div>
                </button>
              ))}
              {videoScenes.length === 0 && <p className="muted small">No scenes yet.</p>}
            </div>
            <div className="stack">
              {selectedVideoScene && (
                <>
                  <label className="stacked-field">
                    Scene title
                    <input
                      className="input"
                      value={sceneTitle(selectedVideoScene as unknown as Record<string, unknown>, "")}
                      onChange={(event) => {
                        const nextScenes = [...videoScenes];
                        nextScenes[selectedVideoSceneIndex] = {
                          ...selectedVideoScene,
                          title: event.target.value,
                          name: event.target.value,
                        };
                        setVideoSpec({ ...activeVideoSpec, scenes: nextScenes });
                      }}
                    />
                  </label>
                  <label className="stacked-field">
                    Voiceover
                    <textarea
                      className="input"
                      rows={5}
                      value={sceneVoiceover(selectedVideoScene as unknown as Record<string, unknown>)}
                      onChange={(event) => {
                        const nextScenes = [...videoScenes];
                        nextScenes[selectedVideoSceneIndex] = {
                          ...selectedVideoScene,
                          voiceover: event.target.value,
                          narration: event.target.value,
                        };
                        setVideoSpec({ ...activeVideoSpec, scenes: nextScenes });
                      }}
                    />
                  </label>
                  <label className="stacked-field">
                    On-screen text
                    <input
                      className="input"
                      value={sceneOnScreen(selectedVideoScene as unknown as Record<string, unknown>)}
                      onChange={(event) => {
                        const nextScenes = [...videoScenes];
                        nextScenes[selectedVideoSceneIndex] = {
                          ...selectedVideoScene,
                          on_screen: event.target.value,
                          on_screen_text: event.target.value,
                        };
                        setVideoSpec({ ...activeVideoSpec, scenes: nextScenes });
                      }}
                    />
                  </label>
                </>
              )}
              <div className="inline-actions">
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => {
                    const next = [
                      ...videoScenes,
                      {
                        id: `s${videoScenes.length + 1}`,
                        title: `Scene ${videoScenes.length + 1}`,
                        name: `Scene ${videoScenes.length + 1}`,
                        duration_seconds: 8,
                        voiceover: "",
                        narration: "",
                        visual_prompt: "",
                        on_screen: "",
                        on_screen_text: "",
                        camera_motion: "",
                        style_constraints: [],
                        generated: { image_asset_url: null, video_clip_url: null },
                      },
                    ];
                    setVideoSpec({ ...activeVideoSpec, scenes: next });
                    setSelectedVideoSceneIndex(next.length - 1);
                  }}
                >
                  <Plus size={14} /> Add scene
                </button>
                <button
                  className="ghost sm"
                  type="button"
                  onClick={() => {
                    if (!selectedVideoScene) return;
                    const next = videoScenes.filter((_, idx) => idx !== selectedVideoSceneIndex);
                    setVideoSpec({ ...activeVideoSpec, scenes: next });
                    setSelectedVideoSceneIndex((current) => Math.max(0, current - 1));
                  }}
                  disabled={!selectedVideoScene}
                >
                  <Trash2 size={14} /> Delete scene
                </button>
                <button className="ghost sm" type="button" onClick={openRegenerateScenesPreview}>
                  Regenerate Scenes…
                </button>
                <button className="primary sm" type="button" onClick={() => void persistVideoSpec(activeVideoSpec)} disabled={videoBusy === "save"}>
                  {videoBusy === "save" ? "Saving…" : "Save scenes"}
                </button>
              </div>
            </div>
          </div>
            )}
            {videoTab === "script" && (
          <div className="stack">
            <p className="muted small">Script is derived from scenes.</p>
            <div className="stack">
              {videoScenes.length === 0 ? (
                <p className="muted small">No scenes available to derive script.</p>
              ) : (
                videoScenes.map((scene, index) => (
                  <section key={`${scene.id || scene.title || scene.name}-${index}`} className="diff-panel">
                    <h4>{sceneTitle(scene as unknown as Record<string, unknown>, `Scene ${index + 1}`)}</h4>
                    <p className="muted small">{sceneOnScreen(scene as unknown as Record<string, unknown>) || "On-screen text not set."}</p>
                    <p>{sceneVoiceover(scene as unknown as Record<string, unknown>) || "Voiceover not set."}</p>
                  </section>
                ))
              )}
            </div>
          </div>
            )}
            {videoTab === "storyboard" && (
          <div className="editor-body split">
            <div className="instance-list">
              {(activeVideoSpec.storyboard?.draft || []).map((scene, index) => (
                <button
                  type="button"
                  key={`${scene.scene}-${index}`}
                  className={`instance-row ${selectedStoryboardSceneIndex === index ? "active" : ""}`}
                  onClick={() => setSelectedStoryboardSceneIndex(index)}
                >
                  <div>
                    <strong>Scene {scene.scene}</strong>
                    <span className="muted small">{scene.time_range}</span>
                  </div>
                </button>
              ))}
              {(activeVideoSpec.storyboard?.draft || []).length === 0 && <p className="muted small">No storyboard scenes yet.</p>}
            </div>
            <div className="stack">
              {selectedStoryboardScene && (
                <>
                  <label className="stacked-field">
                    On-screen text
                    <textarea
                      className="input"
                      rows={3}
                      value={selectedStoryboardScene.on_screen_text || ""}
                      onSelect={(event) => handleStoryboardSelection(event.currentTarget, "on_screen_text", selectedStoryboardSceneIndex)}
                      onChange={(event) => {
                        const nextDraft = [...(activeVideoSpec.storyboard?.draft || [])];
                        nextDraft[selectedStoryboardSceneIndex] = { ...selectedStoryboardScene, on_screen_text: event.target.value };
                        setVideoSpec({
                          ...activeVideoSpec,
                          storyboard: { ...(activeVideoSpec.storyboard || { draft: [] }), draft: nextDraft },
                        });
                      }}
                    />
                  </label>
                  <label className="stacked-field">
                    Visual description
                    <textarea
                      className="input"
                      rows={4}
                      value={selectedStoryboardScene.visual_description || ""}
                      onSelect={(event) => handleStoryboardSelection(event.currentTarget, "visual_description", selectedStoryboardSceneIndex)}
                      onChange={(event) => {
                        const nextDraft = [...(activeVideoSpec.storyboard?.draft || [])];
                        nextDraft[selectedStoryboardSceneIndex] = { ...selectedStoryboardScene, visual_description: event.target.value };
                        setVideoSpec({
                          ...activeVideoSpec,
                          storyboard: { ...(activeVideoSpec.storyboard || { draft: [] }), draft: nextDraft },
                        });
                      }}
                    />
                  </label>
                  <label className="stacked-field">
                    Narration
                    <textarea
                      className="input"
                      rows={4}
                      value={selectedStoryboardScene.narration || ""}
                      onSelect={(event) => handleStoryboardSelection(event.currentTarget, "narration", selectedStoryboardSceneIndex)}
                      onChange={(event) => {
                        const nextDraft = [...(activeVideoSpec.storyboard?.draft || [])];
                        nextDraft[selectedStoryboardSceneIndex] = { ...selectedStoryboardScene, narration: event.target.value };
                        setVideoSpec({
                          ...activeVideoSpec,
                          storyboard: { ...(activeVideoSpec.storyboard || { draft: [] }), draft: nextDraft },
                        });
                      }}
                    />
                  </label>
                </>
              )}
              <div className="inline-actions">
                <button className="ghost sm" type="button" onClick={() => void persistVideoSpec(activeVideoSpec)} disabled={videoBusy === "save"}>
                  Save storyboard
                </button>
                <button
                  className="ghost sm"
                  type="button"
                  onClick={(event) => {
                    const rect = (event.currentTarget as HTMLButtonElement).getBoundingClientRect();
                    openRefinement("storyboard", { top: rect.top, left: rect.left, width: rect.width, height: rect.height });
                  }}
                >
                  <Sparkles size={14} /> Refine
                </button>
                <button
                  className="primary sm"
                  type="button"
                  onClick={() => void generateVideoStoryboardDraft()}
                  disabled={videoBusy === "storyboard"}
                >
                  {videoBusy === "storyboard" ? "Generating…" : "Generate Storyboard"}
                </button>
              </div>
              {pendingSurfaceRefinement?.surface === "storyboard" && (
                <div className="diff-panel">
                  <p className="muted small">Suggestion ready: {pendingSurfaceRefinement.agent_slug || "agent"} · {pendingSurfaceRefinement.provider} {pendingSurfaceRefinement.model}</p>
                  <div className="line-diff article-review-diff">
                    {(computeLineDiff(pendingSurfaceRefinement.baseText, pendingSurfaceRefinement.nextText).ops || []).map((op, idx) => (
                      <pre key={`${idx}-${op.type}`} className={`line-diff-row ${op.type}`}>
                        <span>{op.type === "add" ? "+" : op.type === "remove" ? "-" : " "}</span>
                        {op.text}
                      </pre>
                    ))}
                  </div>
                  <div className="inline-actions">
                    <button className="primary sm" type="button" onClick={applySurfaceRefinement}>
                      Apply changes
                    </button>
                    <button className="ghost sm" type="button" onClick={() => setPendingSurfaceRefinement(null)}>
                      Discard
                    </button>
                  </div>
                </div>
              )}
              {storyboardProposals.length > 0 && (
                <div className="diff-panel">
                  <p className="muted small">Storyboard proposals: {storyboardProposals.length}</p>
                  <button
                    className="ghost sm"
                    type="button"
                    onClick={() => {
                      const first = storyboardProposals[0];
                      if (!first) return;
                      setVideoSpec({
                        ...activeVideoSpec,
                        storyboard: {
                          ...(activeVideoSpec.storyboard || { draft: [], proposals: [] }),
                          draft: (first.storyboard_draft || []) as VideoSpec["storyboard"]["draft"],
                        },
                        scenes: first.scenes || [],
                      });
                    }}
                  >
                    Accept latest proposal
                  </button>
                </div>
              )}
            </div>
          </div>
            )}
            {videoTab === "renders" && (
          <div className="stack">
            {showProviderNotConfigured ? (
              <p className="muted small">
                Video provider is not configured. Render currently produces an export package JSON, not a media file.
              </p>
            ) : null}
            {renderPromptLintHits.length > 0 && (
              <div className="diff-panel">
                <p className="small" style={{ marginBottom: 6 }}>
                  This render may be blocked by provider policy due to real-person references.
                </p>
                <p className="muted small" style={{ marginBottom: 8 }}>
                  Matches: {renderPromptLintHits.slice(0, 4).join(", ")}
                </p>
                <div className="inline-actions">
                  <button className="ghost sm" type="button" onClick={neutralizeRenderPrompt}>
                    Neutralize prompt
                  </button>
                  <button className="ghost sm" type="button" onClick={() => setVideoTab("scenes")}>
                    Edit prompt
                  </button>
                </div>
              </div>
            )}
            <div className="inline-actions">
              <button className="primary sm" type="button" onClick={() => void requestVideoRender()} disabled={videoBusy === "render"}>
                {videoBusy === "render" ? "Queueing…" : showProviderNotConfigured ? "Generate Export Package" : "Render Video"}
              </button>
            </div>
            <div className="instance-list">
              {videoRenders.map((entry) => (
                <div className="instance-row" key={entry.id}>
                  <div>
                    <strong style={entry.status === "filtered" || entry.outcome === "filtered" ? { color: "#f5c26b" } : undefined}>
                      {entry.outcome === "filtered" || entry.status === "filtered" ? "filtered" : entry.status}
                    </strong>
                    <div className="muted small">
                      {entry.provider} · requested {entry.requested_at || "—"}
                    </div>
                    {(entry.context_pack_name || entry.context_pack_id) && (
                      <div className="muted small" style={{ marginTop: 2 }}>
                        · Context pack: {entry.context_pack_name || entry.context_pack_id}
                        {entry.context_pack_version ? ` · v${entry.context_pack_version}` : ""}
                      </div>
                    )}
                    {!!entry.user_message && <div className="muted small" style={{ marginTop: 2 }}>· {entry.user_message}</div>}
                    {!entry.user_message && !!entry.error_message && <div className="muted small" style={{ marginTop: 2 }}>· {entry.error_message}</div>}
                    {(entry.provider_filtered_reasons || []).length > 0 && (
                      <ul className="muted small" style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
                        {(entry.provider_filtered_reasons || []).map((reason, idx) => (
                          <li key={`${entry.id}-reason-${idx}`}>{reason}</li>
                        ))}
                      </ul>
                    )}
                    {(entry.provider_operation_name || entry.provider_response_excerpt) && (
                      <details style={{ marginTop: 6 }}>
                        <summary className="muted small">Technical details</summary>
                        <div className="muted small" style={{ marginTop: 4 }}>
                          {entry.provider_operation_name ? <div>Operation: {entry.provider_operation_name}</div> : null}
                          {entry.provider_error_code ? <div>Error code: {entry.provider_error_code}</div> : null}
                        </div>
                      </details>
                    )}
                    {(entry.output_assets || []).map((asset, idx) => (
                      <a
                        key={`${entry.id}-asset-${idx}`}
                        className="muted small"
                        href={asset.url}
                        target="_blank"
                        rel="noreferrer noopener"
                        style={{ display: "block", marginTop: "2px" }}
                      >
                        {asset.type}: {asset.url}
                      </a>
                    ))}
                  </div>
                  <div className="inline-actions">
                    {(entry.status === "failed" || entry.status === "filtered") && (
                      <button className="ghost sm" type="button" onClick={() => void retryFailedRender(entry.id)} disabled={videoBusy === "retry"}>
                        Retry
                      </button>
                    )}
                    {(entry.status === "filtered" || entry.outcome === "filtered") && (
                      <button className="ghost sm" type="button" onClick={() => setVideoTab("scenes")}>
                        Edit prompt
                      </button>
                    )}
                    {(entry.status === "queued" || entry.status === "running") && (
                      <button className="ghost sm" type="button" onClick={() => void cancelRunningRender(entry.id)} disabled={videoBusy === "cancel"}>
                        Cancel
                      </button>
                    )}
                  </div>
                </div>
              ))}
              {videoRenders.length === 0 && <p className="muted small">No renders yet.</p>}
            </div>
          </div>
            )}
          </>
        )}
      </section>
    ) : null;

  const showRevisionInEditor = activityTab === "revisions" && selectedRevision && revisionMode !== "list";

  const mainSection = (
    <div className="stack">
      {videoEditorPanel}
      <section className={`card article-editor-panel ${articleEditorCollapsed ? "collapsed" : "expanded"}`}>
        <div className="card-header">
          <h4>Article Editor</h4>
          <div className="inline-actions editor-header-actions">
            <span className="muted small editor-drift-text">
              Drift from {baselineLabel}: +{drift.summary.added} / -{drift.summary.removed}
            </span>
            {pendingAssist && (
              <button className={`ghost sm ${editorMode === "review" ? "active" : ""}`} type="button" onClick={() => setEditorMode("review")}>
                Review proposal
              </button>
            )}
            {pendingAssist && editorMode === "review" && (
              <button className="ghost sm" type="button" onClick={() => setEditorMode("edit")}>
                Back to edit
              </button>
            )}
            <button
              className="ghost sm"
              type="button"
              onClick={(event) => {
                const rect = (event.currentTarget as HTMLButtonElement).getBoundingClientRect();
                openRefinement("article", { top: rect.top, left: rect.left, width: rect.width, height: rect.height });
              }}
            >
              <Sparkles size={14} /> Refine
            </button>
            <label className="checkbox-row">
              <input type="checkbox" checked={showPreview} onChange={(event) => setShowPreview(event.target.checked)} />
              Preview
            </label>
            <button
              className="ghost sm"
              type="button"
              aria-label={articleEditorCollapsed ? "Expand article editor" : "Collapse article editor"}
              title={articleEditorCollapsed ? "Expand" : "Collapse"}
              onClick={() => setArticleEditorCollapsed((value) => !value)}
            >
              {articleEditorCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
            </button>
          </div>
        </div>
        {articleEditorCollapsed ? (
          <p className="muted small">Article markdown editor is collapsed. Expand to edit body content and preview.</p>
        ) : (
          <>
            {showRevisionInEditor && selectedRevision && revisionMode === "view" && (
              <section className="diff-panel article-review-panel revision-editor-panel">
                <div className="card-header">
                  <h4>Viewing r{selectedRevision.revision_number}</h4>
                  <button className="ghost sm" type="button" onClick={() => setRevisionMode("list")}>
                    Close
                  </button>
                </div>
                <textarea className="input revision-readonly-textarea" rows={8} value={selectedRevision.body_markdown || ""} readOnly />
                <div className="editor-preview markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(selectedRevision.body_markdown || "") }} />
              </section>
            )}
            {showRevisionInEditor && selectedRevision && revisionMode === "diff" && (
              <section className="diff-panel article-review-panel revision-editor-panel">
                <div className="card-header">
                  <h4>Diff r{selectedRevision.revision_number}</h4>
                  <button className="ghost sm" type="button" onClick={() => setRevisionMode("list")}>
                    Close
                  </button>
                </div>
                <div className="inline-actions">
                  <span className="muted small">Compare against</span>
                  <select value={compareRevisionId} onChange={(event) => setCompareRevisionId(event.target.value)}>
                    <option value="current">Current editor</option>
                    {revisions
                      .filter((entry) => entry.id !== selectedRevision.id)
                      .map((entry) => (
                        <option key={entry.id} value={entry.id}>
                          r{entry.revision_number}
                        </option>
                      ))}
                  </select>
                </div>
                {selectedRevisionDiff && (
                  <p className="muted small">
                    +{selectedRevisionDiff.summary.added} / -{selectedRevisionDiff.summary.removed} lines changed
                  </p>
                )}
                <div className="line-diff article-review-diff">
                  {(selectedRevisionDiff?.ops || []).map((op, idx) => (
                    <pre key={`${idx}-${op.type}`} className={`line-diff-row ${op.type}`}>
                      <span>{op.type === "add" ? "+" : op.type === "remove" ? "-" : " "}</span>
                      {op.text}
                    </pre>
                  ))}
                </div>
              </section>
            )}
            {editorMode === "review" && pendingAssist && !showRevisionInEditor && (
              <section className="diff-panel article-review-panel">
                <div className="card-header">
                  <h4>Suggested edits</h4>
                  <span className="muted small">
                    +{pendingAssistDiff?.summary.added || 0} / -{pendingAssistDiff?.summary.removed || 0} lines
                  </span>
                </div>
                <div className="line-diff article-review-diff">
                  {(pendingAssistDiff?.ops || []).map((op, idx) => (
                    <pre key={`${idx}-${op.type}`} className={`line-diff-row ${op.type}`}>
                      <span>{op.type === "add" ? "+" : op.type === "remove" ? "-" : " "}</span>
                      {op.text}
                    </pre>
                  ))}
                </div>
                <div className="inline-actions">
                  <button className="primary" type="button" onClick={() => void acceptAssist()}>
                    Apply changes
                  </button>
                  <button
                    className="ghost"
                    type="button"
                    onClick={() => {
                      setPendingAssist(null);
                      setEditorMode("edit");
                    }}
                  >
                    Discard
                  </button>
                </div>
              </section>
            )}
            <div className={`editor-body ${showPreview ? "split" : ""} ${missingConsoleFields.has("body") ? "console-missing-field" : ""}`}>
              <MarkdownWysiwygEditor
                value={bodyMarkdown}
                onChange={setBodyMarkdown}
                onSelectionChange={handleEditorSelectionChange}
                ariaLabel="Article editor"
                placeholder="Write the article content..."
                focusSignal={editorFocusSignal}
              />
              {showPreview && <div className="editor-preview markdown-body" dangerouslySetInnerHTML={{ __html: renderMarkdown(bodyMarkdown) }} />}
            </div>
          </>
        )}
      </section>
    </div>
  );

  const floatingRefineTrigger =
    canRefineSelection && activeSelection?.anchorRect && !refinementOpen ? (
      <button
        className="floating-refine-trigger"
        type="button"
        style={{
          top: activeSelection.anchorRect.top + activeSelection.anchorRect.height + 8,
          left: activeSelection.anchorRect.left,
        }}
        onClick={() => openRefinement(selectionSurface || "article", activeSelection.anchorRect || null)}
      >
        <Sparkles size={14} /> Refine
      </button>
    ) : null;

  return (
    <>
      {error ? (
        <div className="card">
          <p className="error-message">{error}</p>
        </div>
      ) : null}
      <EditorCentricLayout
        top={topSection}
        main={mainSection}
        inspector={inspectorPanel}
        activity={activityPanel}
        stickyTop={articleFormat !== "video_explainer"}
      />
      {floatingRefineTrigger}
      <ContextRefinementTool
        open={refinementOpen}
        mobile={isMobileRefinement}
        activeSurface={refinementSurface}
        selectedText={refinementSelectedText}
        videoSpecContext={refinementVideoContext}
        agentOptions={assistAgents}
        selectedAgent={selectedAgent}
        instruction={assistInstruction}
        busy={assistBusy}
        anchorStyle={refinementAnchorStyle}
        onSelectAgent={setSelectedAgent}
        onChangeInstruction={setAssistInstruction}
        onRewrite={() => void runAssist("rewrite_selection", refinementSurface)}
        onSuggest={() =>
          void runAssist(
            refinementSurface === "article" && !isExplainerFormat ? fallbackAssistAction : "propose_edits",
            refinementSurface
          )
        }
        onClose={() => setRefinementOpen(false)}
      />
      {sceneRegenerateOpen && (
        <div className="modal-backdrop" onClick={() => setSceneRegenerateOpen(false)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Regenerate Scenes</h3>
            <p className="muted small" style={{ marginTop: 8 }}>
              Regenerating will replace current scenes. Review the diff before applying.
            </p>
            <div className="line-diff article-review-diff" style={{ marginTop: 12, maxHeight: "320px", overflowY: "auto" }}>
              {(computeLineDiff(JSON.stringify(videoScenes, null, 2), JSON.stringify(sceneRegenerateProposal, null, 2)).ops || []).map((op, idx) => (
                <pre key={`${idx}-${op.type}`} className={`line-diff-row ${op.type}`}>
                  <span>{op.type === "add" ? "+" : op.type === "remove" ? "-" : " "}</span>
                  {op.text}
                </pre>
              ))}
            </div>
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="primary" type="button" onClick={applyRegeneratedScenes}>
                Apply
              </button>
              <button className="ghost" type="button" onClick={() => setSceneRegenerateOpen(false)}>
                Cancel
              </button>
            </div>
          </section>
        </div>
      )}
      {confirmingAction?.confirmation && (
        <div className="modal-backdrop" onClick={() => setConfirmingAction(null)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>{confirmingAction.confirmation.title}</h3>
            <p className="muted" style={{ marginTop: 8 }}>
              {confirmingAction.confirmation.body}
            </p>
            {confirmingAction.id === "publish" && (
              <p className="muted small" style={{ marginTop: 8 }}>
                This action will make the article live on its configured publish targets.
              </p>
            )}
            {confirmingAction.id === "deprecate" && (
              <p className="muted small" style={{ marginTop: 8 }}>
                Deprecated articles are retained for history and audit but removed from active workflows.
              </p>
            )}
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="ghost" type="button" onClick={() => setConfirmingAction(null)}>
                Cancel
              </button>
              <button
                className={confirmingAction.intent === "danger" ? "danger" : "primary"}
                type="button"
                onClick={async () => {
                  const next = confirmingAction;
                  setConfirmingAction(null);
                  await executeAction(next);
                }}
              >
                {confirmingAction.confirmation.confirmLabel}
              </button>
            </div>
          </section>
        </div>
      )}
      {restoreRevisionId && (
        <div className="modal-backdrop" onClick={() => setRestoreRevisionId(null)}>
          <section className="modal" onClick={(event) => event.stopPropagation()}>
            <h3>Restore revision</h3>
            <p className="muted" style={{ marginTop: 8 }}>
              This creates a new revision from the selected historical revision. Existing history is preserved.
            </p>
            {selectedRevisionDiff && (
              <p className="muted small" style={{ marginTop: 8 }}>
                Selected diff summary: +{selectedRevisionDiff.summary.added} / -{selectedRevisionDiff.summary.removed}
              </p>
            )}
            <div className="inline-actions" style={{ marginTop: 12 }}>
              <button className="ghost" type="button" onClick={() => setRestoreRevisionId(null)}>
                Cancel
              </button>
              <button className="primary" type="button" onClick={() => void restoreRevision()}>
                Restore as new revision
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}
