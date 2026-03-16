import { resolveApiBaseUrl } from "../../api/client";
import type { AiActivityEntry, RuntimeRunArtifact, RuntimeRunDetail, RuntimeRunStep, RuntimeRunSummary, RuntimeStreamEvent } from "../../api/types";
import { emitCapabilityEvent } from "../events/emitCapabilityEvent";

const RUNTIME_EVENT_TYPES = [
  "run.started",
  "run.heartbeat",
  "run.step.started",
  "run.step.completed",
  "run.completed",
  "run.failed",
  "run.blocked",
  "run.artifact.created",
] as const;

type RuntimeStreamOptions = {
  workspaceId: string;
  threadId?: string;
  lastEventId?: string;
  since?: string;
  onOpen?: () => void;
  onEvent: (event: RuntimeStreamEvent) => void;
  onError?: () => void;
};

type RuntimeSubscription = {
  close: () => void;
};

function runtimeStreamUrl(workspaceId: string, threadId?: string, lastEventId?: string, since?: string): string {
  const apiBaseUrl = resolveApiBaseUrl();
  const url = new URL(`${apiBaseUrl}/xyn/api/ai/activity/stream`);
  url.searchParams.set("workspace_id", workspaceId);
  if (threadId) url.searchParams.set("thread_id", threadId);
  if (lastEventId) url.searchParams.set("last_event_id", lastEventId);
  if (since) url.searchParams.set("since", since);
  return url.toString();
}

function parseRuntimeStreamEvent(raw: MessageEvent<string>): RuntimeStreamEvent | null {
  try {
    const payload = JSON.parse(String(raw.data || ""));
    if (!payload || typeof payload !== "object") return null;
    return payload as RuntimeStreamEvent;
  } catch {
    return null;
  }
}

function emitCapabilityRefreshForRuntimeEvent(event: RuntimeStreamEvent) {
  const workspaceId = String(event.workspace_id || "").trim() || null;
  if (event.event_type === "run.started") {
    void emitCapabilityEvent({ eventType: "execution_started", workspaceId });
    return;
  }
  if (event.event_type === "run.completed" || event.event_type === "run.failed" || event.event_type === "run.blocked") {
    void emitCapabilityEvent({ eventType: "execution_completed", workspaceId });
    return;
  }
  if (event.event_type === "run.artifact.created") {
    const entityId = String(event.payload?.artifact_id || "").trim() || null;
    void emitCapabilityEvent({ eventType: "artifact_created", entityId, workspaceId });
  }
}

export function subscribeRuntimeEventStream(options: RuntimeStreamOptions): RuntimeSubscription {
  let closed = false;
  let eventSource: EventSource | null = null;
  let reconnectTimer: number | null = null;
  let latestEventId = options.lastEventId || "";

  const connect = () => {
    if (closed) return;
    eventSource = new EventSource(runtimeStreamUrl(options.workspaceId, options.threadId, latestEventId, options.since), { withCredentials: true });
    eventSource.onopen = () => {
      options.onOpen?.();
    };
    const onRuntimeEvent = (raw: Event) => {
      const parsed = parseRuntimeStreamEvent(raw as MessageEvent<string>);
      if (!parsed) return;
      latestEventId = parsed.event_id || latestEventId;
      emitCapabilityRefreshForRuntimeEvent(parsed);
      options.onEvent(parsed);
    };
    for (const eventType of RUNTIME_EVENT_TYPES) {
      eventSource.addEventListener(eventType, onRuntimeEvent as EventListener);
    }
    eventSource.onerror = () => {
      eventSource?.close();
      eventSource = null;
      options.onError?.();
      if (closed) return;
      reconnectTimer = window.setTimeout(connect, 1500);
    };
  };

  connect();

  return {
    close: () => {
      closed = true;
      if (reconnectTimer != null) {
        window.clearTimeout(reconnectTimer);
      }
      eventSource?.close();
    },
  };
}

function activityStatusForEvent(event: RuntimeStreamEvent): "running" | "succeeded" | "failed" {
  if (event.event_type === "run.completed") return "succeeded";
  if (event.event_type === "run.failed" || event.event_type === "run.blocked") return "failed";
  return "running";
}

export function runtimeEventToActivityEntry(event: RuntimeStreamEvent): AiActivityEntry {
  const messageType =
    event.event_type === "run.failed" || event.event_type === "run.blocked"
      ? "escalation"
      : event.event_type === "run.completed"
        ? "execution_summary"
        : "system_runtime";
  return {
    id: `runtime-event:${event.event_id}`,
    event_type: event.event_type,
    status: activityStatusForEvent(event),
    summary: event.message || event.title,
    created_at: event.created_at,
    actor_id: null,
    agent_slug: event.worker_type || "codex_local",
    provider: "",
    model_name: "",
    artifact_id: event.run_id || undefined,
    artifact_type: "runtime_run",
    artifact_title: String(event.payload?.repo || ""),
    request_type: "runtime.run",
    prompt: "",
    workspace_id: event.workspace_id || undefined,
    thread_id: event.thread_id || undefined,
    draft_id: null,
    job_id: null,
    error: String(event.payload?.failure_reason || event.payload?.escalation_reason || ""),
    trace: [],
    structured_operation: {
      run_id: event.run_id,
      worker_type: event.worker_type,
      step_key: event.payload?.step_key,
      artifact_type: event.payload?.artifact_type,
    },
    conversation_message: {
      message_type: messageType,
      title: event.title,
      body: event.message,
      status: event.status || null,
      reason: String(event.payload?.failure_reason || event.payload?.escalation_reason || "") || null,
      options:
        event.event_type === "run.blocked"
          ? ["continue run", "summarize run", "show artifacts"]
          : event.event_type === "run.failed"
            ? ["retry run", "show logs", "show artifacts"]
            : [],
      refs: {
        run_id: event.run_id || null,
        work_item_id: event.work_item_id || null,
        thread_id: event.thread_id || null,
        step_key: String(event.payload?.step_key || "") || null,
        artifact_type: String(event.payload?.artifact_type || "") || null,
        artifact_uri: String(event.payload?.uri || "") || null,
      },
    },
    source: "runtime_event",
  };
}

function sortByTimestampDesc<T extends { created_at?: string | null; id: string }>(items: T[]): T[] {
  return [...items].sort((left, right) => {
    const leftTs = new Date(left.created_at || 0).getTime();
    const rightTs = new Date(right.created_at || 0).getTime();
    if (leftTs !== rightTs) return rightTs - leftTs;
    return String(right.id).localeCompare(String(left.id));
  });
}

export function upsertActivityEntry(items: AiActivityEntry[], next: AiActivityEntry): AiActivityEntry[] {
  const existingIndex = items.findIndex((item) => item.id === next.id);
  const merged = existingIndex >= 0 ? [...items.slice(0, existingIndex), { ...items[existingIndex], ...next }, ...items.slice(existingIndex + 1)] : [...items, next];
  return sortByTimestampDesc(merged);
}

function inferRunSummaryFromEvent(event: RuntimeStreamEvent): RuntimeRunSummary {
  return {
    id: event.run_id || "",
    run_id: event.run_id || "",
    work_item_id: event.work_item_id || null,
    thread_id: event.thread_id || null,
    worker_type: event.worker_type || null,
    worker_id: String(event.payload?.worker_id || "") || null,
    status: String(event.status || event.payload?.status || "queued"),
    summary: String(event.payload?.summary || event.message || event.title || ""),
    created_at: event.created_at,
    queued_at: null,
    started_at: String(event.payload?.started_at || "") || null,
    completed_at: String(event.payload?.completed_at || "") || null,
    heartbeat_at: String(event.payload?.heartbeat_at || "") || null,
    elapsed_time_seconds: null,
    heartbeat_freshness: "missing",
    target: {
      repo: String(event.payload?.repo || "") || null,
      branch: String(event.payload?.branch || "") || null,
      workspace_id: event.workspace_id || null,
      artifact_id: String(event.payload?.artifact_id || "") || null,
    },
    failure_reason: String(event.payload?.failure_reason || "") || null,
    escalation_reason: String(event.payload?.escalation_reason || "") || null,
  };
}

function updateRunSummary(base: RuntimeRunSummary, event: RuntimeStreamEvent): RuntimeRunSummary {
  const baseTerminal = new Set(["succeeded", "failed", "blocked", "completed"]).has(String(base.status || "").toLowerCase());
  const nonTerminalEvent = new Set(["run.started", "run.heartbeat", "run.step.started", "run.step.completed"]).has(event.event_type);
  if (baseTerminal && nonTerminalEvent) {
    return base;
  }
  const next = { ...base };
  if (event.work_item_id) next.work_item_id = event.work_item_id;
  if (event.worker_type) next.worker_type = event.worker_type;
  if (event.status) next.status = event.status;
  if (typeof event.payload?.summary === "string" && event.payload.summary) next.summary = event.payload.summary;
  else if (event.message) next.summary = event.message;
  if (typeof event.payload?.worker_id === "string" && event.payload.worker_id) next.worker_id = event.payload.worker_id;
  if (typeof event.payload?.started_at === "string" && event.payload.started_at) next.started_at = event.payload.started_at;
  if (typeof event.payload?.completed_at === "string" && event.payload.completed_at) next.completed_at = event.payload.completed_at;
  if (typeof event.payload?.heartbeat_at === "string" && event.payload.heartbeat_at) next.heartbeat_at = event.payload.heartbeat_at;
  if (typeof event.payload?.repo === "string" && event.payload.repo) next.target.repo = event.payload.repo;
  if (typeof event.payload?.branch === "string" && event.payload.branch) next.target.branch = event.payload.branch;
  if (typeof event.payload?.failure_reason === "string" && event.payload.failure_reason) next.failure_reason = event.payload.failure_reason;
  if (typeof event.payload?.escalation_reason === "string" && event.payload.escalation_reason) next.escalation_reason = event.payload.escalation_reason;
  return next;
}

export function refreshRuntimeRunSummary(run: RuntimeRunSummary): RuntimeRunSummary {
  const started = run.started_at ? new Date(run.started_at).getTime() : NaN;
  const completed = run.completed_at ? new Date(run.completed_at).getTime() : NaN;
  const heartbeat = run.heartbeat_at ? new Date(run.heartbeat_at).getTime() : NaN;
  const now = Date.now();
  const elapsedTimeSeconds =
    Number.isNaN(started) ? run.elapsed_time_seconds ?? null : Math.max(0, Math.floor(((Number.isNaN(completed) ? now : completed) - started) / 1000));
  let heartbeatFreshness: RuntimeRunSummary["heartbeat_freshness"] = run.heartbeat_freshness || "missing";
  if (!Number.isNaN(heartbeat)) {
    heartbeatFreshness = now - heartbeat <= 30_000 ? "fresh" : "stale";
  }
  return { ...run, elapsed_time_seconds: elapsedTimeSeconds, heartbeat_freshness: heartbeatFreshness };
}

export function applyRuntimeEventToRuns(runs: RuntimeRunSummary[], event: RuntimeStreamEvent): RuntimeRunSummary[] {
  if (!event.run_id) return runs;
  const index = runs.findIndex((run) => run.id === event.run_id);
  const next = index >= 0 ? updateRunSummary(runs[index], event) : inferRunSummaryFromEvent(event);
  const merged = index >= 0 ? [...runs.slice(0, index), refreshRuntimeRunSummary(next), ...runs.slice(index + 1)] : [refreshRuntimeRunSummary(next), ...runs];
  return merged.sort((left, right) => {
    const leftTs = new Date(left.started_at || left.created_at || 0).getTime();
    const rightTs = new Date(right.started_at || right.created_at || 0).getTime();
    if (leftTs !== rightTs) return rightTs - leftTs;
    return String(right.id).localeCompare(String(left.id));
  });
}

export function refreshRuntimeRunDetail(detail: RuntimeRunDetail): RuntimeRunDetail {
  return { ...detail, ...refreshRuntimeRunSummary(detail) };
}

function upsertRunStep(steps: RuntimeRunStep[], step: RuntimeRunStep): RuntimeRunStep[] {
  const index = steps.findIndex((item) => item.id === step.id || (item.step_key === step.step_key && item.sequence_no === step.sequence_no));
  const merged = index >= 0 ? [...steps.slice(0, index), { ...steps[index], ...step }, ...steps.slice(index + 1)] : [...steps, step];
  return merged.sort((left, right) => {
    if (left.sequence_no !== right.sequence_no) return left.sequence_no - right.sequence_no;
    return String(left.id).localeCompare(String(right.id));
  });
}

function upsertRunArtifact(artifacts: RuntimeRunArtifact[], artifact: RuntimeRunArtifact): RuntimeRunArtifact[] {
  const index = artifacts.findIndex((item) => item.id === artifact.id || (item.uri && item.uri === artifact.uri));
  const merged = index >= 0 ? [...artifacts.slice(0, index), { ...artifacts[index], ...artifact }, ...artifacts.slice(index + 1)] : [...artifacts, artifact];
  return merged.sort((left, right) => {
    const leftTs = new Date(left.created_at || 0).getTime();
    const rightTs = new Date(right.created_at || 0).getTime();
    if (leftTs !== rightTs) return leftTs - rightTs;
    return String(left.id).localeCompare(String(right.id));
  });
}

export function applyRuntimeEventToRunDetail(detail: RuntimeRunDetail, event: RuntimeStreamEvent): RuntimeRunDetail {
  if (!event.run_id || detail.id !== event.run_id) return detail;
  const detailTerminal = new Set(["succeeded", "failed", "blocked", "completed"]).has(String(detail.status || "").toLowerCase());
  const nonTerminalEvent = new Set(["run.started", "run.heartbeat", "run.step.started", "run.step.completed"]).has(event.event_type);
  if (detailTerminal && nonTerminalEvent) {
    return detail;
  }
  let next: RuntimeRunDetail = { ...detail, ...refreshRuntimeRunSummary(updateRunSummary(detail, event)) };
  if (event.event_type === "run.step.started" || event.event_type === "run.step.completed") {
    const step: RuntimeRunStep = {
      id: String(event.payload?.step_id || `${detail.id}:${event.payload?.step_key || "step"}`),
      step_key: String(event.payload?.step_key || "step"),
      label: String(event.payload?.label || event.payload?.step_key || "Step"),
      status: String(event.payload?.status || next.status || "running"),
      summary: typeof event.payload?.summary === "string" ? event.payload.summary : null,
      sequence_no: Number(event.payload?.sequence_no || 0),
      started_at: typeof event.payload?.started_at === "string" ? event.payload.started_at : null,
      completed_at: typeof event.payload?.completed_at === "string" ? event.payload.completed_at : null,
    };
    next = { ...next, steps: upsertRunStep(next.steps || [], step) };
  }
  if (event.event_type === "run.artifact.created") {
    const artifact: RuntimeRunArtifact = {
      id: String(event.payload?.artifact_id || `${detail.id}:${event.payload?.artifact_type || "artifact"}`),
      artifact_type: String(event.payload?.artifact_type || "artifact"),
      label: String(event.payload?.label || event.payload?.artifact_type || "Artifact"),
      uri: typeof event.payload?.uri === "string" ? event.payload.uri : null,
      created_at: event.created_at,
      metadata: typeof event.payload === "object" && event.payload ? event.payload : {},
    };
    next = { ...next, artifacts: upsertRunArtifact(next.artifacts || [], artifact) };
  }
  return next;
}
