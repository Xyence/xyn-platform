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
          trace: [],
          structured_operation: { run_id: "run-1", step_key: "inspect_repository" },
        },
      ],
    });

    render(<AgentActivityDrawer open onClose={() => {}} workspaceId="ws-1" />);

    await waitFor(() => expect(apiMocks.listAiActivity).toHaveBeenCalled());
    expect(screen.getByText("Run step completed: inspect repository")).toBeInTheDocument();
    expect(screen.getByText(/runtime\.run/)).toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByText("Run completed · run-1")).toBeInTheDocument());
    expect(screen.getAllByText("Run completed · run-1")).toHaveLength(1);
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
});
