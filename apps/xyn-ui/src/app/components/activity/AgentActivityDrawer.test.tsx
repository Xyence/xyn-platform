import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentActivityDrawer from "./AgentActivityDrawer";

const apiMocks = vi.hoisted(() => ({
  listAiActivity: vi.fn(),
  listAppJobs: vi.fn(),
}));

const streamMocks = vi.hoisted(() => {
  let onEvent: ((event: any) => void) | null = null;
  let onError: (() => void) | null = null;
  return {
    subscribeRuntimeEventStream: vi.fn((options: { onEvent: (event: any) => void; onError?: () => void; onOpen?: () => void }) => {
      onEvent = options.onEvent;
      onError = options.onError || null;
      options.onOpen?.();
      return { close: vi.fn() };
    }),
    emit(event: any) {
      onEvent?.(event);
    },
    fail() {
      onError?.();
    },
  };
});

vi.mock("../../../api/xyn", () => ({
  listAiActivity: apiMocks.listAiActivity,
  listAppJobs: apiMocks.listAppJobs,
}));

vi.mock("../../state/operationRegistry", () => ({
  useOperations: () => ({ operations: [] }),
}));

vi.mock("../../utils/runtimeEventStream", async () => {
  const actual = await vi.importActual<typeof import("../../utils/runtimeEventStream")>("../../utils/runtimeEventStream");
  return {
    ...actual,
    subscribeRuntimeEventStream: streamMocks.subscribeRuntimeEventStream,
  };
});

describe("AgentActivityDrawer runtime activity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.listAppJobs.mockResolvedValue([]);
  });

  it("renders runtime run events from the activity feed", async () => {
    apiMocks.listAiActivity.mockResolvedValue({
      items: [
        {
          id: "runtime-event:1",
          event_type: "run.step.completed",
          status: "running",
          summary: "Run step completed: inspect repository",
          created_at: "2026-03-11T10:00:00Z",
          actor_id: null,
          agent_slug: "codex_local",
          provider: "",
          model_name: "",
          artifact_id: "run-1",
          artifact_type: "runtime_run",
          artifact_title: "xyn",
          request_type: "runtime.run",
          prompt: "",
          workspace_id: "ws-1",
          draft_id: null,
          job_id: null,
          error: "",
          source: "runtime_event",
          conversation_message: {
            message_type: "system_runtime",
            title: "Run step completed: inspect repository",
            body: "Run step completed: inspect repository",
            refs: { run_id: "run-1", work_item_id: "wi-1", step_key: "inspect_repository" },
          },
          trace: [],
          structured_operation: { run_id: "run-1", step_key: "inspect_repository" },
          prompt_interpretation: {
            intent_family: "development_work",
            intent_type: "create_and_dispatch_run",
            action: { verb: "dispatch", label: "Create and dispatch run" },
            fields: [],
            execution_mode: "queued_run",
            confidence: 0.9,
            needs_clarification: false,
            capability_state: { state: "enabled" },
            clarification_options: [],
            resolution_notes: ["reused existing work item"],
            missing_fields: [],
            recognized_spans: [],
            target_work_item: { label: "Epic D", reference: "epic-d" },
            target_run: { id: "run-1", label: "run-1" },
          },
        },
      ],
    });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());
    expect(screen.getAllByText("Run step completed: inspect repository").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/runtime\.run/)).toBeInTheDocument();
    expect(screen.getByText(/run run-1 · work item wi-1 · step inspect_repository/i)).toBeInTheDocument();
    expect(screen.getByText(/Create and dispatch run · Epic D · work item epic-d · run run-1 · queued run/i)).toBeInTheDocument();
    expect(document.querySelectorAll(".notification-item.system-runtime-message")).toHaveLength(1);
  });

  it("renders compact app-operation interpretation details with key fields", async () => {
    apiMocks.listAiActivity.mockResolvedValue({
      items: [
        {
          id: "runtime-event:2",
          event_type: "intent.apply",
          status: "succeeded",
          summary: "Created 1 device: router-1",
          created_at: "2026-03-11T10:00:00Z",
          actor_id: null,
          agent_slug: "xyn",
          provider: "",
          model_name: "",
          artifact_id: null,
          artifact_type: "workspace",
          artifact_title: "",
          request_type: "intent.apply",
          prompt: "create a device called router-1",
          workspace_id: "ws-1",
          draft_id: null,
          job_id: null,
          error: "",
          source: "audit",
          trace: [],
          structured_operation: { entity_key: "devices", operation: "create" },
          prompt_interpretation: {
            intent_family: "app_operation",
            intent_type: "create_record",
            action: { verb: "create", label: "Create record" },
            fields: [
              { name: "name", value: "router-1", kind: "field", state: "resolved" },
              { name: "status", value: "online", kind: "field", state: "resolved" },
            ],
            execution_mode: "immediate_execution",
            confidence: 0.9,
            needs_clarification: false,
            capability_state: { state: "enabled" },
            clarification_options: [],
            resolution_notes: [],
            missing_fields: [],
            recognized_spans: [],
            target_entity: { label: "devices" },
            target_record: { reference: "router-1" },
          },
        },
      ],
    });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());
    expect(screen.getByText(/Create record · devices · router-1 · name=router-1, status=online · immediate execution/i)).toBeInTheDocument();
  });

  it("renders run-supervision interpretation details compactly", async () => {
    apiMocks.listAiActivity.mockResolvedValue({
      items: [
        {
          id: "runtime-event:3",
          event_type: "intent.resolve",
          status: "succeeded",
          summary: "failure status requested",
          created_at: "2026-03-11T10:00:00Z",
          actor_id: null,
          agent_slug: "xyn",
          provider: "",
          model_name: "",
          artifact_id: null,
          artifact_type: "workspace",
          artifact_title: "",
          request_type: "intent.resolve",
          prompt: "show me what failed",
          workspace_id: "ws-1",
          draft_id: null,
          job_id: null,
          error: "",
          source: "audit",
          trace: [],
          structured_operation: {},
          prompt_interpretation: {
            intent_family: "run_supervision",
            intent_type: "show_status",
            action: { verb: "show", label: "Show status" },
            fields: [],
            execution_mode: "immediate_execution",
            confidence: 0.86,
            needs_clarification: false,
            capability_state: { state: "unknown" },
            clarification_options: [],
            resolution_notes: ["failure status requested"],
            missing_fields: [],
            recognized_spans: [],
            target_run: { id: "run-9", label: "run-9", status: "failed" },
          },
        },
      ],
    });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());
    expect(screen.getByText(/Show status · run-9 · run run-9 · immediate execution/i)).toBeInTheDocument();
  });

  it("appends live streamed runtime activity and de-duplicates reconnect replay", async () => {
    apiMocks.listAiActivity.mockResolvedValue({ items: [] });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());

    const event = {
      event_id: "evt-1",
      event_type: "run.completed",
      created_at: "2026-03-11T10:00:00Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "succeeded",
      title: "Run completed · run-1",
      message: "Run completed · run-1",
      payload: { repo: "xyn", summary: "done" },
    };

    act(() => {
      streamMocks.emit(event);
      streamMocks.emit(event);
    });

    await waitFor(() => expect(screen.getByText(/run run-1 · work item wi-1/i)).toBeInTheDocument());
    expect(document.querySelectorAll(".notification-item.system-runtime-message")).toHaveLength(1);
  });

  it("falls back to periodic refresh when the stream degrades", async () => {
    apiMocks.listAiActivity.mockResolvedValue({ items: [] });
    const setIntervalSpy = vi.spyOn(window, "setInterval").mockImplementation((handler: TimerHandler) => {
      if (typeof handler === "function") handler();
      return 1 as unknown as number;
    });
    const clearIntervalSpy = vi.spyOn(window, "clearInterval").mockImplementation(() => undefined);
    try {
      render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);
      await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalledTimes(1));

      act(() => {
        streamMocks.fail();
      });
      expect(screen.getByText(/Falling back to periodic refresh/)).toBeInTheDocument();
      await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalledTimes(2));
      expect(setIntervalSpy).toHaveBeenCalled();
    } finally {
      setIntervalSpy.mockRestore();
      clearIntervalSpy.mockRestore();
    }
  }, 10000);

  it("renders escalation and execution summary conversation messages compactly", async () => {
    apiMocks.listAiActivity.mockResolvedValue({
      items: [
        {
          id: "runtime-event:4",
          event_type: "run.failed",
          status: "failed",
          summary: "Run failed",
          created_at: "2026-03-11T10:00:00Z",
          actor_id: null,
          agent_slug: "codex_local",
          provider: "",
          model_name: "",
          artifact_id: "run-1",
          artifact_type: "runtime_run",
          artifact_title: "xyn-platform",
          request_type: "runtime.run",
          prompt: "",
          workspace_id: "ws-1",
          draft_id: null,
          job_id: null,
          error: "tests_failed",
          source: "runtime_event",
          conversation_message: {
            message_type: "escalation",
            title: "Run failed",
            body: "Run failed: tests_failed",
            reason: "tests_failed",
            options: ["retry run", "show logs", "show artifacts"],
            refs: { run_id: "run-1", work_item_id: "wi-1" },
          },
          trace: [],
          structured_operation: { run_id: "run-1" },
        },
        {
          id: "runtime-event:5",
          event_type: "run.completed",
          status: "succeeded",
          summary: "Run completed · run-2",
          created_at: "2026-03-11T10:01:00Z",
          actor_id: null,
          agent_slug: "codex_local",
          provider: "",
          model_name: "",
          artifact_id: "run-2",
          artifact_type: "runtime_run",
          artifact_title: "xyn-platform",
          request_type: "runtime.run",
          prompt: "",
          workspace_id: "ws-1",
          draft_id: null,
          job_id: null,
          error: "",
          source: "runtime_event",
          conversation_message: {
            message_type: "execution_summary",
            title: "Run completed · run-2",
            body: "Run completed · run-2",
            options: [],
            refs: { run_id: "run-2", work_item_id: "wi-2" },
          },
          trace: [],
          structured_operation: { run_id: "run-2" },
        },
      ],
    });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());
    expect(screen.getByText(/Run failed: tests_failed/)).toBeInTheDocument();
    expect(screen.getByText(/retry run · show logs · show artifacts/i)).toBeInTheDocument();
    expect(screen.getByText(/run run-2 · work item wi-2/i)).toBeInTheDocument();
  });
});
