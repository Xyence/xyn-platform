import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkbenchPanelHost from "./WorkbenchPanelHost";
import { emitEntityChange } from "../../utils/entityChangeEvents";

const apiMocks = vi.hoisted(() => ({
  executeAppPalettePrompt: vi.fn(),
  listGoals: vi.fn(),
  getGoal: vi.fn(),
  reviewGoal: vi.fn(),
  reviewCoordinationThread: vi.fn(),
  listCoordinationThreads: vi.fn(),
  getCoordinationThread: vi.fn(),
  getWorkQueue: vi.fn(),
  listRuntimeRunsCanvasApi: vi.fn(),
  getRuntimeRunCanvasApi: vi.fn(),
  listWorkItems: vi.fn(),
  getWorkItem: vi.fn(),
  getRuntimeRunArtifactContent: vi.fn(),
}));

const streamMocks = vi.hoisted(() => {
  let onEvent: ((event: any) => void) | null = null;
  let onError: (() => void) | null = null;
  return {
    subscribeRuntimeEventStream: vi.fn((options: { onEvent: (event: any) => void; onError?: () => void }) => {
      onEvent = options.onEvent;
      onError = options.onError || null;
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

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    executeAppPalettePrompt: apiMocks.executeAppPalettePrompt,
    listGoals: apiMocks.listGoals,
    getGoal: apiMocks.getGoal,
    reviewGoal: apiMocks.reviewGoal,
    reviewCoordinationThread: apiMocks.reviewCoordinationThread,
    listCoordinationThreads: apiMocks.listCoordinationThreads,
    getCoordinationThread: apiMocks.getCoordinationThread,
    getWorkQueue: apiMocks.getWorkQueue,
    listRuntimeRunsCanvasApi: apiMocks.listRuntimeRunsCanvasApi,
    getRuntimeRunCanvasApi: apiMocks.getRuntimeRunCanvasApi,
    listWorkItems: apiMocks.listWorkItems,
    getWorkItem: apiMocks.getWorkItem,
    getRuntimeRunArtifactContent: apiMocks.getRuntimeRunArtifactContent,
  };
});

vi.mock("../../state/notificationsStore", () => ({
  useNotifications: () => ({ push: vi.fn() }),
}));

vi.mock("../../utils/runtimeEventStream", async () => {
  const actual = await vi.importActual<typeof import("../../utils/runtimeEventStream")>("../../utils/runtimeEventStream");
  return {
    ...actual,
    subscribeRuntimeEventStream: streamMocks.subscribeRuntimeEventStream,
  };
});

describe("WorkbenchPanelHost entity refresh", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads work items from durable work item API and opens detail targets", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.listWorkItems.mockResolvedValue({
      count: 1,
      next: null,
      prev: null,
      work_items: [
        {
          id: "task-1",
          work_item_id: "wi-1",
          title: "Implement Epic H",
          status: "running",
          target_repo: "xyn-platform",
          updated_at: "2026-03-12T12:00:00Z",
          task_type: "codegen",
          priority: 0,
          attempts: 0,
          max_attempts: 2,
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "wi-list", panel_type: "table", instance_key: "work_items", key: "work_items" }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.listWorkItems).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText("Implement Epic H")).toBeInTheDocument());
  });

  it("loads XCO thread summaries and derived queue data", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.listCoordinationThreads.mockResolvedValue({
      count: 1,
      next: null,
      prev: null,
      threads: [
        {
          id: "thread-1",
          workspace_id: "ws-1",
          title: "Runtime Refactor",
          description: "",
          owner: null,
          priority: "high",
          status: "active",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: { max_concurrent_runs: 1 },
          source_conversation_id: "thread-conversation-1",
          queued_work_items: 1,
          running_work_items: 0,
          awaiting_review_work_items: 0,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-12T10:00:00Z",
          updated_at: "2026-03-12T10:00:00Z",
        },
      ],
    });
    apiMocks.getWorkQueue.mockResolvedValue({
      workspace_id: "ws-1",
      items: [
        {
          thread_id: "thread-1",
          work_item_id: "wi-1",
          task_id: "task-1",
          thread_priority: "high",
          thread_title: "Runtime Refactor",
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "thread-list", panel_type: "table", instance_key: "thread-list", key: "thread_list", params: { workspace_id: "ws-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.listCoordinationThreads).toHaveBeenCalledWith("ws-1"));
    await waitFor(() => expect(apiMocks.getWorkQueue).toHaveBeenCalledWith("ws-1"));
    await waitFor(() => expect(screen.getAllByText("Runtime Refactor")).toHaveLength(2));
    expect(screen.getByText("wi-1")).toBeInTheDocument();
  });

  it("loads durable goals and opens goal detail targets", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.listGoals.mockResolvedValue({
      count: 1,
      next: null,
      prev: null,
      goals: [
        {
          id: "goal-1",
          workspace_id: "ws-1",
          title: "AI Real Estate Deal Finder",
          description: "Build a deal finder using listings and comps.",
          goal_type: "build_system",
          planning_status: "decomposed",
          priority: "high",
          planning_summary: "Start with listing ingestion and property CRUD.",
          resolution_notes: ["Bias toward MVP-first slices."],
          thread_count: 2,
          work_item_count: 3,
          created_at: "2026-03-12T10:00:00Z",
          updated_at: "2026-03-12T10:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "goal-list", panel_type: "table", instance_key: "goal-list", key: "goal_list", params: { workspace_id: "ws-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.listGoals).toHaveBeenCalledWith("ws-1"));
    await waitFor(() => expect(screen.getByText("AI Real Estate Deal Finder")).toBeInTheDocument());
  });

  it("loads durable goal detail with threads, work items, and recommendation", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.reviewGoal.mockResolvedValue({
      status: "approved",
      goal: {
        id: "goal-1",
        workspace_id: "ws-1",
        title: "AI Real Estate Deal Finder",
        description: "Build a deal finder using listings and comps.",
        goal_type: "build_system",
        planning_status: "in_progress",
        priority: "high",
        planning_summary: "Start with listing ingestion and property CRUD.",
        resolution_notes: ["Bias toward MVP-first slices."],
        thread_count: 2,
        work_item_count: 3,
        created_at: "2026-03-12T10:00:00Z",
        updated_at: "2026-03-12T10:00:00Z",
        threads: [],
        work_items: [],
        recommendation: null,
        development_loop_summary: {
          goal_status: "in_progress",
          threads: [],
          recent_work_results: [],
          recommended_next_slice: null,
        },
      },
    });
    apiMocks.getGoal.mockResolvedValue({
      id: "goal-1",
      workspace_id: "ws-1",
      title: "AI Real Estate Deal Finder",
      description: "Build a deal finder using listings and comps.",
      goal_type: "build_system",
      planning_status: "in_progress",
      priority: "high",
      planning_summary: "Start with listing ingestion and property CRUD.",
      resolution_notes: ["Bias toward MVP-first slices."],
      thread_count: 2,
      work_item_count: 3,
      created_at: "2026-03-12T10:00:00Z",
      updated_at: "2026-03-12T10:00:00Z",
      threads: [
        {
          id: "thread-1",
          workspace_id: "ws-1",
          title: "Listing Data Ingestion",
          description: "",
          priority: "high",
          status: "active",
          domain: "data",
          work_in_progress_limit: 1,
          execution_policy: {},
          queued_work_items: 1,
          running_work_items: 0,
          awaiting_review_work_items: 0,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-12T10:00:00Z",
          updated_at: "2026-03-12T10:00:00Z",
        },
      ],
      work_items: [
        {
          id: "task-1",
          work_item_id: "goal-wi-1",
          title: "Identify the first listing source and capture the ingestion contract",
          status: "queued",
          target_repo: "xyn-platform",
          task_type: "codegen",
          priority: 100,
          attempts: 0,
          max_attempts: 3,
        },
      ],
      recommendation: {
        recommendation_id: "rec:v1:goal-1:thread-1:task-1:queue_first_slice:abcd1234",
        goal_id: "goal-1",
        thread_id: "thread-1",
        thread_title: "Listing Data Ingestion",
        work_item_id: "task-1",
        work_item_title: "Identify the first listing source and capture the ingestion contract",
        actions: [
          {
            type: "approve_and_queue",
            label: "Approve and Queue",
            target_thread: "thread-1",
            target_work_item: "task-1",
            queueable: true,
          },
          {
            type: "review_thread",
            label: "Review Thread",
            target_thread: "thread-1",
            target_work_item: null,
            queueable: false,
          },
        ],
        summary: "Queue the next smallest slice from Listing Data Ingestion.",
      },
      development_loop_summary: {
        goal_status: "in_progress",
        threads: [
          {
            thread_id: "thread-1",
            title: "Listing Data Ingestion",
            thread_status: "active",
          },
        ],
        recent_work_results: [
          {
            work_item_id: "goal-wi-1",
            title: "Identify the first listing source and capture the ingestion contract",
            status: "queued",
            run_id: null,
            artifact_count: 1,
          },
        ],
        recommended_next_slice: {
          recommendation_id: "rec:v1:goal-1:thread-1:task-1:queue_first_slice:abcd1234",
          goal_id: "goal-1",
          thread_id: "thread-1",
          thread_title: "Listing Data Ingestion",
          work_item_id: "task-1",
          work_item_title: "Identify the first listing source and capture the ingestion contract",
          summary: "Queue the next smallest slice from Listing Data Ingestion.",
        },
      },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "goal-detail", panel_type: "detail", instance_key: "goal:goal-1", key: "goal_detail", params: { goal_id: "goal-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getGoal).toHaveBeenCalledWith("goal-1"));
    await waitFor(() => expect(screen.getByText("AI Real Estate Deal Finder")).toBeInTheDocument());
    expect(screen.getAllByText("Listing Data Ingestion").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Development Loop")).toBeInTheDocument();
    expect(screen.getAllByText("in_progress").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Artifacts")).toBeInTheDocument();
    expect(screen.getAllByText("Identify the first listing source and capture the ingestion contract").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Queue the next smallest slice from Listing Data Ingestion.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve and Queue" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "View Thread" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Review Work Items" })).toBeEnabled();

    await act(async () => {
      screen.getByRole("button", { name: "Approve and Queue" }).click();
    });
    await waitFor(() =>
      expect(apiMocks.reviewGoal).toHaveBeenCalledWith(
        "goal-1",
        "approve_and_queue",
        "rec:v1:goal-1:thread-1:task-1:queue_first_slice:abcd1234",
      ),
    );
    expect(screen.getByText("Approved and queued the recommended slice.")).toBeInTheDocument();
  });

  it("loads XCO thread detail with work item, run, artifact, and timeline navigation", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.reviewCoordinationThread.mockResolvedValue({
      status: "approved",
      summary: "Approved the next slice for Runtime Refactor.",
      thread: {
        id: "thread-1",
        workspace_id: "ws-1",
        title: "Runtime Refactor",
        description: "Refactor runtime queue handling",
        owner: null,
        priority: "high",
        status: "active",
        domain: "development",
        work_in_progress_limit: 1,
        execution_policy: { max_concurrent_runs: 1 },
        source_conversation_id: "thread-conversation-1",
        thread_progress_status: "active",
        work_items_completed: 0,
        work_items_ready: 1,
        work_items_blocked: 0,
        queued_work_items: 1,
        running_work_items: 1,
        awaiting_review_work_items: 0,
        completed_work_items: 0,
        failed_work_items: 0,
        recent_run_ids: ["run-1"],
        created_at: "2026-03-12T10:00:00Z",
        updated_at: "2026-03-12T10:00:00Z",
        work_items: [
          {
            id: "task-1",
            work_item_id: "wi-1",
            title: "Implement scheduler",
            status: "running",
            target_repo: "xyn-platform",
            runtime_run_id: "run-1",
            task_type: "codegen",
            priority: 0,
            attempts: 0,
            max_attempts: 2,
          },
        ],
        recent_runs: [
          {
            id: "run-1",
            status: "running",
            summary: "Scheduler refactor is running",
            error: null,
            log_text: "",
            started_at: "2026-03-12T10:05:00Z",
            finished_at: null,
            failure_reason: null,
            escalation_reason: null,
          },
        ],
        recent_artifacts: [
          {
            id: "artifact-1",
            run_id: "run-1",
            work_item_id: "wi-1",
            artifact_type: "summary",
            label: "Final summary",
            uri: "artifact://runs/run-1/final_summary.md",
            created_at: "2026-03-12T10:10:00Z",
          },
        ],
        timeline: [
          {
            id: "evt-1",
            event_type: "run_dispatched_from_queue",
            work_item_id: "wi-1",
            run_id: "run-1",
            payload: {},
            created_at: "2026-03-12T10:05:00Z",
          },
        ],
      },
    });
    apiMocks.getCoordinationThread.mockResolvedValue({
      id: "thread-1",
      workspace_id: "ws-1",
      title: "Runtime Refactor",
      description: "Refactor runtime queue handling",
      owner: null,
      priority: "high",
      status: "active",
      domain: "development",
      work_in_progress_limit: 1,
      execution_policy: { max_concurrent_runs: 1 },
      source_conversation_id: "thread-conversation-1",
      thread_progress_status: "active",
      work_items_completed: 0,
      work_items_ready: 1,
      work_items_blocked: 0,
      queued_work_items: 0,
      running_work_items: 1,
      awaiting_review_work_items: 0,
      completed_work_items: 0,
      failed_work_items: 0,
      recent_run_ids: ["run-1"],
      created_at: "2026-03-12T10:00:00Z",
      updated_at: "2026-03-12T10:00:00Z",
      work_items: [
        {
          id: "task-1",
          work_item_id: "wi-1",
          title: "Implement scheduler",
          status: "running",
          target_repo: "xyn-platform",
          runtime_run_id: "run-1",
          task_type: "codegen",
          priority: 0,
          attempts: 0,
          max_attempts: 2,
        },
      ],
      recent_runs: [
        {
          id: "run-1",
          status: "running",
          summary: "Scheduler refactor is running",
          error: null,
          log_text: "",
          started_at: "2026-03-12T10:05:00Z",
          finished_at: null,
          failure_reason: null,
          escalation_reason: null,
        },
      ],
      recent_artifacts: [
        {
          id: "artifact-1",
          run_id: "run-1",
          work_item_id: "wi-1",
          artifact_type: "summary",
          label: "Final summary",
          uri: "artifact://runs/run-1/final_summary.md",
          created_at: "2026-03-12T10:10:00Z",
        },
      ],
      timeline: [
        {
          id: "evt-1",
          event_type: "run_dispatched_from_queue",
          work_item_id: "wi-1",
          run_id: "run-1",
          payload: {},
          created_at: "2026-03-12T10:05:00Z",
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "thread-detail", panel_type: "detail", instance_key: "thread-1", key: "thread_detail", params: { thread_id: "thread-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getCoordinationThread).toHaveBeenCalledWith("thread-1"));
    await waitFor(() => expect(screen.getByText("Implement scheduler")).toBeInTheDocument());
    expect(screen.getByText("run_dispatched_from_queue")).toBeInTheDocument();
    expect(screen.getByText("Final summary")).toBeInTheDocument();
    expect(screen.getByText("Thread Review")).toBeInTheDocument();
    expect(screen.getByText("Scheduler refactor is running")).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "Queue Next Slice" }).click();
    });

    await waitFor(() => expect(apiMocks.reviewCoordinationThread).toHaveBeenCalledWith("thread-1", "queue_next_slice"));
    expect(screen.getByText("Approved the next slice for Runtime Refactor.")).toBeInTheDocument();
  });

  it("loads runtime artifact content for runtime-backed artifact detail panels", async () => {
    apiMocks.getRuntimeRunArtifactContent.mockResolvedValue({
      artifact_id: "artifact-1",
      run_id: "run-1",
      artifact_type: "summary",
      label: "final_summary.md",
      uri: "artifact://runs/run-1/final_summary.md",
      content_type: "text/markdown",
      content: "Run finished successfully.",
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "artifact-panel",
            panel_type: "detail",
            instance_key: "runtime-artifact",
            key: "artifact_detail",
            params: { runtime_run_id: "run-1", runtime_artifact_id: "artifact-1" },
          }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getRuntimeRunArtifactContent).toHaveBeenCalledWith("ws-1", "run-1", "artifact-1"));
    await waitFor(() => expect(screen.getByText("Run finished successfully.")).toBeInTheDocument());
  });

  it("reloads a visible matching entity table after an entity change", async () => {
    apiMocks.executeAppPalettePrompt.mockResolvedValue({
      kind: "table",
      columns: ["id", "name", "status"],
      rows: [{ id: "dev-2", name: "router-2", status: "offline" }],
      text: "Found 1 devices.",
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "panel-1",
            panel_type: "table",
            instance_key: "palette_result",
            title: "Palette Result",
            key: "palette_result",
            params: {
              prompt: "show devices",
              result: {
                kind: "table",
                columns: ["id", "name", "status"],
                rows: [{ id: "dev-1", name: "router-1", status: "online" }],
                text: "Found 1 devices.",
              },
            },
          }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    expect(screen.getByText("router-1")).toBeInTheDocument();
    act(() => {
      emitEntityChange({ entityKey: "devices", operation: "update", source: "palette" });
    });

    await waitFor(() => expect(apiMocks.executeAppPalettePrompt).toHaveBeenCalledWith("ws-1", { prompt: "show devices" }));
    await waitFor(() => expect(screen.getByText("router-2")).toBeInTheDocument());
  });

  it("does not reload when a different entity changes", async () => {
    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "panel-1",
            panel_type: "table",
            instance_key: "palette_result",
            title: "Palette Result",
            key: "palette_result",
            params: {
              prompt: "show devices",
              result: {
                kind: "table",
                columns: ["id", "name", "status"],
                rows: [{ id: "dev-1", name: "router-1", status: "online" }],
                text: "Found 1 devices.",
              },
            },
          }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    act(() => {
      emitEntityChange({ entityKey: "locations", operation: "delete", source: "palette" });
    });

    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(apiMocks.executeAppPalettePrompt).not.toHaveBeenCalled();
    expect(screen.getByText("router-1")).toBeInTheDocument();
  });

  it("shows runtime run status, elapsed time, and heartbeat freshness", async () => {
    apiMocks.listRuntimeRunsCanvasApi.mockResolvedValue({
      runs: [
        {
          id: "run-1",
          run_id: "run-1",
          work_item_id: "wi-1",
          worker_type: "codex_local",
          worker_id: "worker-1",
          status: "running",
          summary: "Implementing runtime worker",
          created_at: "2026-03-11T10:00:00Z",
          started_at: "2026-03-11T10:00:05Z",
          completed_at: null,
          heartbeat_at: "2026-03-11T10:00:10Z",
          elapsed_time_seconds: 42,
          heartbeat_freshness: "fresh",
          target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "runs-1", panel_type: "table", instance_key: "runs", key: "runs" }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.listRuntimeRunsCanvasApi).toHaveBeenCalledWith("ws-1", undefined));
    await waitFor(() => expect(screen.getByText("wi-1")).toBeInTheDocument());
    expect(screen.getByText("codex_local")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
    expect(screen.getByText("42s")).toBeInTheDocument();
    expect(screen.getByText("fresh")).toBeInTheDocument();
  });

  it("updates the runs panel live from streamed runtime events", async () => {
    apiMocks.listRuntimeRunsCanvasApi.mockResolvedValue({
      runs: [
        {
          id: "run-live",
          run_id: "run-live",
          work_item_id: "wi-live",
          worker_type: "codex_local",
          worker_id: "worker-1",
          status: "queued",
          summary: "Queued",
          created_at: "2026-03-11T10:00:00Z",
          started_at: null,
          completed_at: null,
          heartbeat_at: null,
          elapsed_time_seconds: 0,
          heartbeat_freshness: "missing",
          target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost workspaceId="ws-1" panel={{ panel_id: "runs-live", panel_type: "table", instance_key: "runs", key: "runs" }} onOpenPanel={() => {}} />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("queued")).toBeInTheDocument());

    act(() => {
      streamMocks.emit({
        event_id: "evt-1",
        event_type: "run.started",
        created_at: "2026-03-11T10:00:05Z",
        workspace_id: "ws-1",
        run_id: "run-live",
        work_item_id: "wi-live",
        worker_type: "codex_local",
        status: "running",
        title: "Run started · run-live",
        message: "Run started · run-live",
        payload: { worker_id: "worker-1", started_at: "2026-03-11T10:00:05Z", status: "running", summary: "Running" },
      });
    });

    await waitFor(() => expect(screen.getByText("running")).toBeInTheDocument());
  });

  it("shows runtime run timeline, artifacts, and escalation details", async () => {
    apiMocks.getRuntimeRunCanvasApi.mockResolvedValue({
      id: "run-2",
      run_id: "run-2",
      work_item_id: "wi-2",
      worker_type: "codex_local",
      worker_id: "worker-2",
      status: "blocked",
      summary: "Need review",
      created_at: "2026-03-11T10:00:00Z",
      started_at: "2026-03-11T10:00:05Z",
      completed_at: null,
      heartbeat_at: "2026-03-11T10:00:10Z",
      elapsed_time_seconds: 15,
      heartbeat_freshness: "stale",
      target: { repo: "xyn-platform", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      failure_reason: null,
      escalation_reason: "contract ambiguity",
      prompt: { title: "Fix runtime worker", body: "Do the work" },
      policy: { auto_continue: true, max_retries: 1, require_human_review_on_failure: true, timeout_seconds: 1800 },
      steps: [
        {
          id: "step-1",
          step_key: "inspect_repository",
          label: "Inspect repository",
          status: "completed",
          summary: "Repo inspected",
          sequence_no: 1,
          started_at: "2026-03-11T10:00:06Z",
          completed_at: "2026-03-11T10:00:07Z",
        },
      ],
      artifacts: [
        {
          id: "artifact-1",
          artifact_type: "summary",
          label: "Final summary",
          uri: "artifact://runs/run-2/final_summary.md",
          created_at: "2026-03-11T10:00:20Z",
          metadata: {},
        },
      ],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "run-2", panel_type: "detail", instance_key: "run:run-2", key: "run_detail", params: { run_id: "run-2" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getRuntimeRunCanvasApi).toHaveBeenCalledWith("ws-1", "run-2"));
    await waitFor(() => expect(screen.getByText("contract ambiguity")).toBeInTheDocument());
    expect(screen.getByText("Inspect repository")).toBeInTheDocument();
    expect(screen.getByText("Final summary")).toBeInTheDocument();
  });

  it("shows failure reason for failed runtime runs", async () => {
    apiMocks.getRuntimeRunCanvasApi.mockResolvedValue({
      id: "run-3",
      run_id: "run-3",
      work_item_id: "wi-3",
      worker_type: "codex_local",
      worker_id: "worker-3",
      status: "failed",
      summary: "Tests failed",
      created_at: "2026-03-11T10:00:00Z",
      started_at: "2026-03-11T10:00:05Z",
      completed_at: "2026-03-11T10:01:00Z",
      heartbeat_at: "2026-03-11T10:00:30Z",
      elapsed_time_seconds: 55,
      heartbeat_freshness: "stale",
      target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      failure_reason: "tests_failed",
      escalation_reason: null,
      prompt: { title: "Run tests", body: "Run the suite" },
      policy: { auto_continue: false, max_retries: 0, require_human_review_on_failure: false, timeout_seconds: 1800 },
      steps: [],
      artifacts: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "run-3", panel_type: "detail", instance_key: "run:run-3", key: "run_detail", params: { run_id: "run-3" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("tests_failed")).toBeInTheDocument());
  });

  it("updates run detail live for steps and artifacts without duplicates", async () => {
    apiMocks.getRuntimeRunCanvasApi.mockResolvedValue({
      id: "run-stream",
      run_id: "run-stream",
      work_item_id: "wi-stream",
      worker_type: "codex_local",
      worker_id: "worker-3",
      status: "running",
      summary: "Running",
      created_at: "2026-03-11T10:00:00Z",
      started_at: "2026-03-11T10:00:05Z",
      completed_at: null,
      heartbeat_at: "2026-03-11T10:00:10Z",
      elapsed_time_seconds: 5,
      heartbeat_freshness: "fresh",
      target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      failure_reason: null,
      escalation_reason: null,
      prompt: { title: "Run tests", body: "Run the suite" },
      policy: { auto_continue: false, max_retries: 0, require_human_review_on_failure: false, timeout_seconds: 1800 },
      steps: [],
      artifacts: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "run-stream", panel_type: "detail", instance_key: "run:run-stream", key: "run_detail", params: { run_id: "run-stream" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getRuntimeRunCanvasApi).toHaveBeenCalledWith("ws-1", "run-stream"));

    const stepEvent = {
      event_id: "evt-step-1",
      event_type: "run.step.completed",
      created_at: "2026-03-11T10:00:06Z",
      workspace_id: "ws-1",
      run_id: "run-stream",
      work_item_id: "wi-stream",
      worker_type: "codex_local",
      status: "running",
      title: "Run step completed: inspect repository",
      message: "Run step completed: inspect repository",
      payload: {
        step_id: "step-stream-1",
        step_key: "inspect_repository",
        label: "Inspect repository",
        sequence_no: 1,
        status: "completed",
        summary: "Repo inspected",
      },
    };
    const artifactEvent = {
      event_id: "evt-artifact-1",
      event_type: "run.artifact.created",
      created_at: "2026-03-11T10:00:07Z",
      workspace_id: "ws-1",
      run_id: "run-stream",
      work_item_id: "wi-stream",
      worker_type: "codex_local",
      status: "running",
      title: "Run artifact created",
      message: "Run artifact created: summary",
      payload: {
        artifact_id: "artifact-stream-1",
        artifact_type: "summary",
        label: "Final summary",
        uri: "artifact://runs/run-stream/final_summary.md",
      },
    };

    act(() => {
      streamMocks.emit(stepEvent);
      streamMocks.emit(stepEvent);
      streamMocks.emit(artifactEvent);
      streamMocks.emit(artifactEvent);
    });

    await waitFor(() => expect(screen.getByText("Inspect repository")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Final summary")).toBeInTheDocument());
    expect(screen.getAllByText("Inspect repository")).toHaveLength(1);
    expect(screen.getAllByText("Final summary")).toHaveLength(1);
  });

  it("does not render duplicate panel chrome headings or close buttons", async () => {
    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "platform-1", panel_type: "detail", instance_key: "platform_settings", key: "platform_settings" }}
          onOpenPanel={() => {}}
          onClosePanel={vi.fn()}
        />
      </MemoryRouter>
    );

    expect(screen.queryByRole("button", { name: "Close" })).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Platform Settings" })).toBeInTheDocument();
  });
});
