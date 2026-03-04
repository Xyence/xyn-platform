import { useEffect, useMemo, useState } from "react";
import {
  completeWorkflowRun,
  executeWorkflowAction,
  getTour,
  logWorkflowRunEvent,
  startWorkflowRun,
} from "../../../api/xyn";
import type { TourDefinition, WorkflowStep } from "../../../api/types";

type TourOverlayProps = {
  userKey: string;
  launchSlug: string | null;
  launchToken: number;
  currentPath: string;
  navigateTo: (path: string) => void;
  onClose: () => void;
  canRecord?: boolean;
};

type PersistedState = {
  index: number;
  dismissed: boolean;
  completed: boolean;
};

function normalizePath(path: string): string {
  const trimmed = (path || "").trim();
  if (!trimmed) return "/";
  return trimmed.endsWith("/") && trimmed !== "/" ? trimmed.slice(0, -1) : trimmed;
}

function routeMatchesCurrentPath(stepRoute: string, currentPath: string): boolean {
  const expected = normalizePath(stepRoute);
  const current = normalizePath(currentPath);
  return current === expected || current.startsWith(`${expected}/`);
}

function storageKey(userKey: string, slug: string): string {
  return `xyn.tour.progress.${slug}.${userKey || "anon"}`;
}

function loadProgress(userKey: string, slug: string): PersistedState {
  try {
    const raw = localStorage.getItem(storageKey(userKey, slug));
    if (!raw) return { index: 0, dismissed: false, completed: false };
    return {
      index: 0,
      dismissed: false,
      completed: false,
      ...(JSON.parse(raw) as Partial<PersistedState>),
    };
  } catch {
    return { index: 0, dismissed: false, completed: false };
  }
}

function saveProgress(userKey: string, slug: string, state: PersistedState): void {
  try {
    localStorage.setItem(storageKey(userKey, slug), JSON.stringify(state));
  } catch {
    // ignore storage failures
  }
}

export function loadTourProgressForTest(userKey: string, slug: string): PersistedState {
  return loadProgress(userKey, slug);
}

export function saveTourProgressForTest(userKey: string, slug: string, state: PersistedState): void {
  saveProgress(userKey, slug, state);
}

function resolveAnchorElement(step: WorkflowStep): Element | null {
  const anchor = step.anchor || {};
  const testId = String(anchor.test_id || "").trim();
  if (testId) {
    const byTestId = document.querySelector(`[data-testid=\"${CSS.escape(testId)}\"]`);
    if (byTestId) return byTestId;
  }
  const anchorId = String(anchor.anchor_id || "").trim();
  if (anchorId) {
    const byAnchorId = document.querySelector(`[data-anchor-id=\"${CSS.escape(anchorId)}\"]`);
    if (byAnchorId) return byAnchorId;
  }
  const selector = String(anchor.selector || "").trim();
  if (selector) {
    try {
      return document.querySelector(selector);
    } catch {
      return null;
    }
  }
  return null;
}

export default function TourOverlay({ userKey, launchSlug, launchToken, currentPath, navigateTo, onClose, canRecord = false }: TourOverlayProps) {
  const [tour, setTour] = useState<TourDefinition | null>(null);
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  const [persisted, setPersisted] = useState<PersistedState>({ index: 0, dismissed: false, completed: false });
  const [attachedToSelector, setAttachedToSelector] = useState(true);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [runId, setRunId] = useState<string>("");
  const [recordMode, setRecordMode] = useState(false);
  const [hoverInfo, setHoverInfo] = useState<{ route: string; testId: string; anchorId: string; selector: string }>({ route: "", testId: "", anchorId: "", selector: "" });

  const step = useMemo(() => {
    if (!tour) return null;
    return tour.steps[index] || null;
  }, [tour, index]);

  useEffect(() => {
    let cancelled = false;
    if (!launchSlug || launchToken === 0) return;
    (async () => {
      try {
        const definition = await getTour(launchSlug);
        if (cancelled) return;
        const progress = loadProgress(userKey, definition.slug);
        const nextIndex = Math.min(progress.index || 0, Math.max(0, definition.steps.length - 1));
        setTour(definition);
        setIndex(nextIndex);
        setPersisted(progress);
        setOpen(true);
        setFeedback(null);
        const run = await startWorkflowRun(definition.workflow_id);
        if (!cancelled) setRunId(run.run.id);
        const targetRoute = definition.steps[nextIndex]?.route;
        if (targetRoute && !routeMatchesCurrentPath(targetRoute, currentPath)) {
          navigateTo(targetRoute);
        }
      } catch (err) {
        if (!cancelled) {
          setOpen(false);
          setFeedback((err as Error).message || "Could not launch tour.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [launchSlug, launchToken, userKey, currentPath, navigateTo]);

  useEffect(() => {
    if (!open || !step || !tour) return;
    if (step.route && !routeMatchesCurrentPath(step.route, currentPath)) {
      navigateTo(step.route);
      return;
    }
    let highlighted: Element | null = null;
    const found = resolveAnchorElement(step);
    if (step.anchor && Object.keys(step.anchor).length > 0 && !found) {
      setAttachedToSelector(false);
    } else {
      setAttachedToSelector(true);
    }
    if (found && step.ui?.highlight !== false) {
      highlighted = found;
      highlighted.classList.add("tour-highlighted");
      if (highlighted instanceof HTMLElement) {
        highlighted.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
    if (runId) {
      void logWorkflowRunEvent(tour.workflow_id, runId, {
        step_id: step.id,
        type: "step_viewed",
        payload_json: { route: step.route || currentPath, anchor_found: Boolean(found) },
      });
    }
    return () => {
      if (highlighted) highlighted.classList.remove("tour-highlighted");
    };
  }, [open, step, tour, runId, currentPath, navigateTo]);

  useEffect(() => {
    if (!recordMode) return;
    const onMove = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const testId = target.closest("[data-testid]")?.getAttribute("data-testid") || "";
      const anchorId = target.closest("[data-anchor-id]")?.getAttribute("data-anchor-id") || "";
      const selector = target.tagName ? `${target.tagName.toLowerCase()}${target.id ? `#${target.id}` : ""}` : "";
      setHoverInfo({ route: currentPath, testId, anchorId, selector });
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [recordMode, currentPath]);

  const persist = (patch: Partial<PersistedState>) => {
    if (!tour) return;
    const current = loadProgress(userKey, tour.slug);
    const next = { ...current, ...patch };
    saveProgress(userKey, tour.slug, next);
    setPersisted(next);
  };

  const closeTour = async (dismissed: boolean, completed = false) => {
    if (tour) {
      persist({ dismissed, index, completed });
      if (runId) {
        await completeWorkflowRun(tour.workflow_id, runId, completed ? "completed" : "aborted");
      }
    }
    setOpen(false);
    onClose();
  };

  const nextStep = () => {
    if (!tour) return;
    const next = index + 1;
    if (next >= tour.steps.length) {
      void closeTour(false, true);
      return;
    }
    setIndex(next);
    persist({ index: next, dismissed: false, completed: false });
    setFeedback(null);
  };

  const previousStep = () => {
    if (!step?.ui?.allow_back && index === 0) return;
    const next = Math.max(0, index - 1);
    setIndex(next);
    if (tour) persist({ index: next });
    setFeedback(null);
  };

  const restartTour = () => {
    if (!tour) return;
    setIndex(0);
    persist({ index: 0, dismissed: false, completed: false });
    setFeedback(null);
  };

  const runActionStep = async () => {
    if (!tour || !step || step.type !== "action") return;
    try {
      const result = await executeWorkflowAction({
        action_id: String(step.action_id || "").trim(),
        params: step.params || {},
        idempotency_key: step.idempotency_key_template || `${tour.slug}:${step.id}`,
      });
      setFeedback(step.success_toast || (result.ok ? "Action completed." : "Action finished."));
      if (runId) {
        await logWorkflowRunEvent(tour.workflow_id, runId, {
          step_id: step.id,
          type: "action_executed",
          payload_json: { action_id: step.action_id || "", ok: result.ok },
        });
      }
    } catch (err) {
      setFeedback((err as Error).message || "Action failed.");
      if (runId) {
        await logWorkflowRunEvent(tour.workflow_id, runId, {
          step_id: step.id,
          type: "action_failed",
          payload_json: { action_id: step.action_id || "" },
        });
      }
    }
  };

  const runCopyStep = async () => {
    if (!tour || !step || step.type !== "copy") return;
    try {
      await navigator.clipboard.writeText(String(step.clipboard_text || ""));
      setFeedback(step.toast_on_copy || "Copied to clipboard.");
      if (runId) {
        await logWorkflowRunEvent(tour.workflow_id, runId, {
          step_id: step.id,
          type: "copied",
          payload_json: { length: String(step.clipboard_text || "").length },
        });
      }
    } catch {
      setFeedback("Copy failed.");
    }
  };

  if (!open || !tour || !step) return null;

  return (
    <div className="tour-overlay" role="dialog" aria-label="Workflow tour runner">
      <div className="tour-card" data-testid="tour-runner-card">
        <div className="tour-header">
          <h4>{tour.title}</h4>
          <span className="muted small">Step {index + 1} / {tour.steps.length}</span>
        </div>
        <h5>{step.title}</h5>
        <p>{step.body_md}</p>
        {!attachedToSelector && (
          <div className="muted small">
            Can't find the target element on this screen.
            <div className="inline-actions">
              <button className="ghost small" onClick={() => setIndex((prev) => prev)}>Retry</button>
              {(tour.settings?.allow_skip ?? true) && <button className="ghost small" onClick={nextStep}>Skip</button>}
            </div>
          </div>
        )}
        {step.type === "action" && (
          <div className="inline-actions">
            <button className="ghost small" onClick={() => void runActionStep()}>Run action</button>
          </div>
        )}
        {step.type === "copy" && (
          <div className="inline-actions">
            <button className="ghost small" onClick={() => void runCopyStep()}>Copy text</button>
          </div>
        )}
        {feedback && <p className="muted small">{feedback}</p>}
        <div className="tour-actions">
          <button className="ghost small" onClick={() => void closeTour(true, false)}>
            Exit
          </button>
          <button className="ghost small" onClick={restartTour}>
            Restart
          </button>
          <button className="ghost small" onClick={previousStep} disabled={index === 0 || step.ui?.allow_back === false}>
            Back
          </button>
          <button className="primary" onClick={nextStep}>
            {index + 1 >= tour.steps.length ? "Finish" : "Next"}
          </button>
        </div>
        {canRecord && (
          <div className="stack" style={{ marginTop: 12 }}>
            <label className="inline-actions">
              <input type="checkbox" checked={recordMode} onChange={(event) => setRecordMode(event.target.checked)} />
              <span className="muted small">Record mode</span>
            </label>
            {recordMode && (
              <div className="xyn-ledger">
                <div>route: <code>{hoverInfo.route || currentPath}</code></div>
                <div>data-testid: <code>{hoverInfo.testId || "(none)"}</code></div>
                <div>data-anchor-id: <code>{hoverInfo.anchorId || "(none)"}</code></div>
                <div>element: <code>{hoverInfo.selector || "(none)"}</code></div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
