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
  getApplicationPlan: vi.fn(),
  applyApplicationPlan: vi.fn(),
  getComposerState: vi.fn(),
  generateApplicationPlan: vi.fn(),
  getApplication: vi.fn(),
  updateApplication: vi.fn(),
  updateApplicationPlan: vi.fn(),
  reviewCoordinationThread: vi.fn(),
  listCoordinationThreads: vi.fn(),
  getCoordinationThread: vi.fn(),
  getWorkQueue: vi.fn(),
  dispatchNextWorkQueueItem: vi.fn(),
  dispatchWorkItem: vi.fn(),
  publishDevTask: vi.fn(),
  retryDevTask: vi.fn(),
  requeueDevTask: vi.fn(),
  listRuntimeRunsCanvasApi: vi.fn(),
  getRuntimeRunCanvasApi: vi.fn(),
  listWorkItems: vi.fn(),
  getWorkItem: vi.fn(),
  updateWorkItem: vi.fn(),
  getRuntimeRunArtifactContent: vi.fn(),
  getSystemReadiness: vi.fn(),
  getExecutionPlan: vi.fn(),
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
    getApplicationPlan: apiMocks.getApplicationPlan,
    applyApplicationPlan: apiMocks.applyApplicationPlan,
    getComposerState: apiMocks.getComposerState,
    generateApplicationPlan: apiMocks.generateApplicationPlan,
    getApplication: apiMocks.getApplication,
    updateApplication: apiMocks.updateApplication,
    updateApplicationPlan: apiMocks.updateApplicationPlan,
    reviewCoordinationThread: apiMocks.reviewCoordinationThread,
    listCoordinationThreads: apiMocks.listCoordinationThreads,
    getCoordinationThread: apiMocks.getCoordinationThread,
    getWorkQueue: apiMocks.getWorkQueue,
    dispatchNextWorkQueueItem: apiMocks.dispatchNextWorkQueueItem,
    dispatchWorkItem: apiMocks.dispatchWorkItem,
    publishDevTask: apiMocks.publishDevTask,
    retryDevTask: apiMocks.retryDevTask,
    requeueDevTask: apiMocks.requeueDevTask,
    listRuntimeRunsCanvasApi: apiMocks.listRuntimeRunsCanvasApi,
    getRuntimeRunCanvasApi: apiMocks.getRuntimeRunCanvasApi,
    listWorkItems: apiMocks.listWorkItems,
    getWorkItem: apiMocks.getWorkItem,
    updateWorkItem: apiMocks.updateWorkItem,
    getRuntimeRunArtifactContent: apiMocks.getRuntimeRunArtifactContent,
    getSystemReadiness: apiMocks.getSystemReadiness,
    getExecutionPlan: apiMocks.getExecutionPlan,
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
    apiMocks.getSystemReadiness.mockResolvedValue({
      ready: false,
      summary: "Configuration required",
      checks: [
        {
          component: "coding_agents",
          status: "missing",
          message: "No enabled coding agents are configured.",
        },
      ],
      paths: {
        workspace_root: "/app/workspaces",
        artifact_root: "/app/media",
      },
    });
    apiMocks.getExecutionPlan.mockResolvedValue({
      capability_id: "build_application",
      architecture: {
        interface: "Xyn language interface",
        database: "PostgreSQL",
        deployment: "Kubernetes service",
      },
      defaults: {
        interface: "Xyn language interface",
        database: "PostgreSQL",
        deployment: "Kubernetes service",
      },
      dependencies: ["FastAPI", "SQLAlchemy"],
      components: ["application_service", "data_models", "api_endpoints"],
      generated_commands: [],
      artifacts: ["application"],
    });
  });

  it("shows system readiness diagnostics in the workbench shell", async () => {
    apiMocks.listWorkItems.mockResolvedValue({
      count: 0,
      next: null,
      prev: null,
      work_items: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "work-items", panel_type: "table", instance_key: "work-items", key: "work_items" }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getSystemReadiness).toHaveBeenCalled());
    expect(screen.getByText("System Readiness")).toBeInTheDocument();
    expect(screen.getByText("Configuration required")).toBeInTheDocument();
    expect(screen.getByText(/No enabled coding agents are configured\./)).toBeInTheDocument();
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
          queue_state: {
            queue_ready: true,
            dispatchable: true,
            dispatched: false,
            blocked: false,
            status: "queue_ready",
            reason: null,
            message: "Task is approved and ready for queue dispatch.",
          },
        },
      ],
    });
    apiMocks.dispatchNextWorkQueueItem.mockResolvedValue({
      status: "dispatched",
      queue_item: { thread_id: "thread-1", work_item_id: "wi-1", task_id: "task-1" },
      run_id: "run-1",
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
    expect(screen.getByText("Task is approved and ready for queue dispatch.")).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "Dispatch Next" }).click();
    });
    await waitFor(() => expect(apiMocks.dispatchNextWorkQueueItem).toHaveBeenCalledWith("ws-1"));
    expect(screen.getByText("Dispatched wi-1.")).toBeInTheDocument();
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
      portfolio_state: {
        goals: [
          {
            goal_id: "goal-1",
            title: "AI Real Estate Deal Finder",
            planning_status: "decomposed",
            goal_progress_status: "in_progress",
            progress_percent: 25,
            health_status: "active",
            active_threads: 1,
            blocked_threads: 0,
            recent_execution_count: 2,
            coordination_priority: {
              value: "medium",
              reasons: ["Goal has active execution or queueable progress but no blocking condition."],
            },
          },
        ],
        insights: [
          {
            key: "steady_progress",
            summary: "Portfolio activity is balanced with AI Real Estate Deal Finder showing the strongest current forward progress.",
            evidence: ["AI Real Estate Deal Finder is at 25% progress with 1 active thread."],
            goal_ids: ["goal-1"],
          },
        ],
        recommended_goal: {
          goal_id: "goal-1",
          title: "AI Real Estate Deal Finder",
          coordination_priority: "medium",
          summary: "Queue the next smallest slice from Listing Data Ingestion.",
          reasoning: "Goal has active execution or queueable progress but no blocking condition.",
          thread_id: "thread-1",
          work_item_id: "task-1",
          queue_action_type: "queue_first_slice",
        },
      },
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
    expect(screen.getByText(/Recommended Goal: AI Real Estate Deal Finder/i)).toBeInTheDocument();
    expect(screen.getByText(/Portfolio activity is balanced/i)).toBeInTheDocument();
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
          change_set: {
            available: true,
            status: "changed",
            has_changes: true,
            source: "workspace",
            repository_slug: "xyn-platform",
            changed_file_count: 1,
            files: [{ path: "services/ingestion.py", change_type: "modified", patch_available: true }],
            patch_available: true,
            message: "1 file changed in the managed workspace.",
          },
          execution_brief_review: {
            has_brief: true,
            review_state: "draft",
            revision: 1,
            history_count: 0,
            summary: "Bound the listing-ingestion coding handoff",
            objective: "Keep the first slice focused on the ingestion contract.",
            target_repository_slug: "xyn-platform",
            target_branch: "develop",
            gated: true,
            ready: false,
            blocked: true,
            blocked_reason: "brief_not_ready",
            blocked_message: "Execution brief review is required before coding execution can proceed.",
            review_notes: "Needs human review",
            available_actions: ["mark_ready", "approve", "reject", "regenerate"],
          },
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
      goal_progress: {
        goal_progress_status: "in_progress",
        completed_work_items: 0,
        active_work_items: 1,
        blocked_work_items: 0,
        active_threads: 1,
        blocked_threads: 0,
        artifact_production_count: 1,
      },
      metrics: {
        active_threads: 1,
        blocked_threads: 0,
        total_completed_work_items: 0,
        artifact_production_count: 1,
      },
      goal_health: {
        progress_percent: 33,
        active_threads: 1,
        blocked_threads: 0,
        recent_artifacts: 1,
      },
      goal_diagnostic: {
        status: "active",
        observations: ["Listing ingestion remains the primary execution path."],
        contributing_threads: [
          { thread_id: "thread-1", title: "Listing Data Ingestion", status: "active" },
        ],
        evidence: ["1 active thread and 0 blocked threads are contributing current progress."],
        suggested_human_review_focus: "Confirm the ingestion thread keeps moving before broadening scope.",
      },
      development_insights: [
        {
          key: "steady_progress",
          summary: "Development activity appears steady without a dominant operational issue right now.",
          evidence: ["1 work item completed across 1 active and 0 blocked thread(s)."],
        },
      ],
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
    expect(screen.getByText("Goal Health")).toBeInTheDocument();
    expect(screen.getByText("Goal Diagnostic")).toBeInTheDocument();
    expect(screen.getByText("Listing ingestion remains the primary execution path.")).toBeInTheDocument();
    expect(screen.getByText("Development Insights")).toBeInTheDocument();
    expect(screen.getByText("Development activity appears steady without a dominant operational issue right now.")).toBeInTheDocument();
    expect(screen.getByText("33%")).toBeInTheDocument();
    expect(screen.getAllByText("Active Threads").length).toBeGreaterThan(0);
    expect(screen.getByText("Artifacts Produced")).toBeInTheDocument();
    expect(screen.getAllByText("in_progress").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Artifacts")).toBeInTheDocument();
    expect(screen.getAllByText("Identify the first listing source and capture the ingestion contract").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("1 file changed")).toBeInTheDocument();
    expect(screen.getByText("Draft · blocked")).toBeInTheDocument();
    expect(screen.getByText("Execution brief review is required before coding execution can proceed.")).toBeInTheDocument();
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

  it("loads composer discovery state with factory catalog", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "factory_discovery",
      context: { factory_key: null, application_plan_id: null, application_id: null, goal_id: null, thread_id: null },
      factory_catalog: [
        { key: "ai_real_estate_deal_finder", name: "AI Real Estate Deal Finder", description: "Deal sourcing workflow", use_case: "real estate" },
      ],
      application_plans: [],
      applications: [],
      related_goals: [],
      related_threads: [],
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getComposerState).toHaveBeenCalledWith({ workspace_id: "ws-1" }));
    expect(screen.getByText("Application Efforts")).toBeInTheDocument();
    expect(screen.getByText("Workflow status")).toBeInTheDocument();
    expect(screen.getByText("No active build in progress")).toBeInTheDocument();
    expect(screen.getByText("Start a new application plan.")).toBeInTheDocument();
    expect(screen.getByText("AI Real Estate Deal Finder")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Generate Plan" })).toBeInTheDocument();
  });

  it("groups composer work under application efforts and isolates unlinked coordination items", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "application_overview",
      context: { factory_key: null, application_plan_id: null, application_id: "app-2", goal_id: null, thread_id: null },
      factory_catalog: [],
      application_plans: [
        {
          id: "plan-1",
          name: "Knowledgebase Plan",
          status: "review",
          source_factory_key: "generic_application_mvp",
          summary: "Plan ready for review",
          request_objective: "Build a personal knowledgebase",
          created_at: "2026-03-16T15:00:00Z",
          updated_at: "2026-03-16T15:00:00Z",
        },
      ],
      applications: [
        {
          id: "app-1",
          name: "Lunch Poll",
          status: "active",
          source_factory_key: "generic_application_mvp",
          summary: "Older lunch app effort",
          request_objective: "Build a lunch poll app",
          goal_count: 1,
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T11:00:00Z",
        },
        {
          id: "app-2",
          name: "Knowledgebase",
          status: "active",
          source_factory_key: "generic_application_mvp",
          summary: "Current app effort",
          request_objective: "Build a personal knowledgebase",
          goal_count: 1,
          created_at: "2026-03-16T10:00:00Z",
          updated_at: "2026-03-16T16:00:00Z",
        },
      ],
      application: {
        id: "app-2",
        name: "Knowledgebase",
        status: "active",
        source_factory_key: "generic_application_mvp",
        summary: "Current app effort",
        request_objective: "Build a personal knowledgebase",
        goal_count: 1,
        goals: [],
        created_at: "2026-03-16T10:00:00Z",
        updated_at: "2026-03-16T16:00:00Z",
      },
      related_goals: [
        {
          id: "goal-1",
          application_id: "app-1",
          title: "Workflow and Stabilization",
          planning_status: "decomposed",
          goal_progress_status: "blocked",
          thread_count: 1,
          work_item_count: 2,
          planning_summary: "Repair the lunch app workflow.",
          resolution_notes: [],
          created_at: "2026-03-15T11:05:00Z",
          updated_at: "2026-03-15T11:05:00Z",
        },
        {
          id: "goal-legacy",
          application_id: null,
          title: "Legacy cleanup",
          planning_status: "decomposed",
          goal_progress_status: "active",
          thread_count: 1,
          work_item_count: 1,
          planning_summary: "Unlinked work.",
          resolution_notes: [],
          created_at: "2026-03-14T10:00:00Z",
          updated_at: "2026-03-14T10:10:00Z",
        },
      ],
      related_threads: [
        {
          id: "thread-1",
          workspace_id: "ws-1",
          goal_id: "goal-1",
          goal_title: "Workflow and Stabilization",
          title: "Smoke test",
          description: "",
          owner: null,
          priority: "high",
          status: "active",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: {},
          source_conversation_id: "conv-1",
          queued_work_items: 0,
          running_work_items: 0,
          awaiting_review_work_items: 1,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-15T11:06:00Z",
          updated_at: "2026-03-15T11:06:00Z",
        },
        {
          id: "thread-legacy",
          workspace_id: "ws-1",
          goal_id: "goal-legacy",
          goal_title: "Legacy cleanup",
          title: "Cleanup slice",
          description: "",
          owner: null,
          priority: "normal",
          status: "queued",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: {},
          source_conversation_id: "conv-0",
          queued_work_items: 1,
          running_work_items: 0,
          awaiting_review_work_items: 0,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-14T10:11:00Z",
          updated_at: "2026-03-14T10:11:00Z",
        },
      ],
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer-grouped", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1", application_id: "app-2" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getComposerState).toHaveBeenCalled());
    expect(screen.getByText("Current Work Context")).toBeInTheDocument();
    expect(screen.getByText("Application Efforts")).toBeInTheDocument();
    expect(screen.getAllByText("Knowledgebase").length).toBeGreaterThan(0);
    expect(screen.queryByText("Lunch Poll")).not.toBeInTheDocument();
    await act(async () => {
      screen.getByRole("button", { name: "Failed (1)" }).click();
    });
    expect(screen.getByText("Lunch Poll")).toBeInTheDocument();
    expect(screen.getByText("Unlinked Work")).toBeInTheDocument();
    expect(screen.getAllByText("Legacy cleanup").length).toBeGreaterThan(0);
  });

  it("filters stale failed efforts out of the default active view and restores them in the failed filter", async () => {
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "application_overview",
      context: { factory_key: null, application_plan_id: null, application_id: "app-2", goal_id: null, thread_id: null },
      factory_catalog: [],
      application_plans: [],
      applications: [
        {
          id: "app-1",
          name: "Lunch Poll",
          status: "active",
          source_factory_key: "generic_application_mvp",
          summary: "Older lunch app effort",
          request_objective: "Build a lunch poll app",
          goal_count: 1,
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T11:00:00Z",
        },
        {
          id: "app-2",
          name: "Knowledgebase",
          status: "active",
          source_factory_key: "generic_application_mvp",
          summary: "Current app effort",
          request_objective: "Build a personal knowledgebase",
          goal_count: 0,
          created_at: "2026-03-16T10:00:00Z",
          updated_at: "2026-03-16T16:00:00Z",
        },
      ],
      application: {
        id: "app-2",
        name: "Knowledgebase",
        status: "active",
        source_factory_key: "generic_application_mvp",
        summary: "Current app effort",
        request_objective: "Build a personal knowledgebase",
        goal_count: 0,
        goals: [],
        created_at: "2026-03-16T10:00:00Z",
        updated_at: "2026-03-16T16:00:00Z",
      },
      related_goals: [
        {
          id: "goal-1",
          application_id: "app-1",
          title: "Workflow and Stabilization",
          planning_status: "decomposed",
          goal_progress_status: "blocked",
          thread_count: 1,
          work_item_count: 2,
          planning_summary: "Repair the lunch app workflow.",
          resolution_notes: [],
          created_at: "2026-03-15T11:05:00Z",
          updated_at: "2026-03-15T11:05:00Z",
        },
      ],
      related_threads: [
        {
          id: "thread-1",
          workspace_id: "ws-1",
          goal_id: "goal-1",
          goal_title: "Workflow and Stabilization",
          title: "Smoke test",
          description: "",
          owner: null,
          priority: "high",
          status: "active",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: {},
          source_conversation_id: "conv-1",
          queued_work_items: 0,
          running_work_items: 0,
          awaiting_review_work_items: 1,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-15T11:06:00Z",
          updated_at: "2026-03-15T11:06:00Z",
        },
      ],
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer-filtered", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1", application_id: "app-2" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getComposerState).toHaveBeenCalled());
    expect(screen.queryByText("Lunch Poll")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Failed (1)" })).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "Failed (1)" }).click();
    });

    expect(screen.getByText("Lunch Poll")).toBeInTheDocument();
  });

  it("archives and restarts application efforts through lifecycle controls", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "application_overview",
      context: { factory_key: null, application_plan_id: null, application_id: "app-1", goal_id: null, thread_id: null },
      factory_catalog: [],
      application_plans: [],
      applications: [
        {
          id: "app-1",
          name: "Lunch Poll",
          status: "active",
          source_factory_key: "generic_application_mvp",
          summary: "Current app effort",
          request_objective: "Build a lunch poll app",
          goal_count: 0,
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T11:00:00Z",
        },
      ],
      application: {
        id: "app-1",
        name: "Lunch Poll",
        status: "active",
        source_factory_key: "generic_application_mvp",
        summary: "Current app effort",
        request_objective: "Build a lunch poll app",
        goal_count: 0,
        goals: [],
        created_at: "2026-03-15T10:00:00Z",
        updated_at: "2026-03-15T11:00:00Z",
      },
      related_goals: [],
      related_threads: [],
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    });
    apiMocks.updateApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-1",
      name: "Lunch Poll",
      summary: "Current app effort",
      source_factory_key: "generic_application_mvp",
      status: "archived",
      request_objective: "Build a lunch poll app",
      goal_count: 0,
      goals: [],
      created_at: "2026-03-15T10:00:00Z",
      updated_at: "2026-03-15T11:00:00Z",
    });
    apiMocks.generateApplicationPlan.mockResolvedValue({
      id: "plan-2",
      workspace_id: "ws-1",
      application_id: null,
      name: "Lunch Poll",
      summary: "Fresh reviewable plan",
      source_factory_key: "generic_application_mvp",
      status: "review",
      request_objective: "Build a lunch poll app",
      created_at: "2026-03-16T16:00:00Z",
      updated_at: "2026-03-16T16:00:00Z",
      generated_plan: {
        application_name: "Lunch Poll",
        application_summary: "Fresh reviewable plan",
        source_factory_key: "generic_application_mvp",
        request_objective: "Build a lunch poll app",
        ordering_hints: [],
        dependency_hints: [],
        resolution_notes: [],
        generated_goals: [],
      },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer-restart", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1", application_id: "app-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getComposerState).toHaveBeenCalled());

    await act(async () => {
      screen.getAllByRole("button", { name: "Start Over" })[0].click();
    });

    await waitFor(() =>
      expect(apiMocks.generateApplicationPlan).toHaveBeenCalledWith({
        workspace_id: "ws-1",
        objective: "Build a lunch poll app",
        factory_key: "generic_application_mvp",
        application_name: "Lunch Poll",
      }),
    );
    await waitFor(() => expect(apiMocks.updateApplication).toHaveBeenCalledWith("app-1", { status: "archived" }));
    expect(onOpenPanel).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "composer_detail",
        params: expect.objectContaining({
          workspace_id: "ws-1",
          application_plan_id: "plan-2",
          factory_key: "generic_application_mvp",
        }),
      }),
    );
  });

  it("loads composer plan review state and applies plans through the existing plan seam", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "plan_review",
      context: { factory_key: "ai_real_estate_deal_finder", application_plan_id: "plan-1", application_id: null, goal_id: null, thread_id: null },
      factory_catalog: [],
      selected_factory: { key: "ai_real_estate_deal_finder", name: "AI Real Estate Deal Finder", description: "Deal sourcing workflow", use_case: "real estate" },
      application_plans: [],
      applications: [],
      application_plan: {
        id: "plan-1",
        name: "Deal Finder",
        status: "review",
        source_factory_key: "ai_real_estate_deal_finder",
        summary: "Reviewable plan",
        generated_goals: [{ title: "Listing and Property Foundation", planning_summary: "Start with ingestion", threads: [], work_items: [] }],
        factory: { key: "ai_real_estate_deal_finder", name: "AI Real Estate Deal Finder", description: "Deal sourcing workflow", use_case: "real estate" },
      },
      related_goals: [],
      related_threads: [],
      breadcrumbs: [{ kind: "composer", label: "Composer" }, { kind: "application_plan", label: "Deal Finder", id: "plan-1" }],
      available_actions: [{ type: "apply_plan", label: "Apply Plan", enabled: true, target_kind: "application_plan", target_id: "plan-1" }],
    });
    apiMocks.applyApplicationPlan.mockResolvedValue({
      status: "applied",
      application: { id: "app-1", name: "Deal Finder", status: "active", source_factory_key: "ai_real_estate_deal_finder", summary: "Deal Finder", goal_count: 1, goals: [] },
      application_plan: { id: "plan-1", name: "Deal Finder", status: "applied", source_factory_key: "ai_real_estate_deal_finder", summary: "Reviewable plan", generated_goals: [] },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1", application_plan_id: "plan-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getAllByText("Deal Finder").length).toBeGreaterThan(0));
    expect(screen.getByText("Selected Application Plan")).toBeInTheDocument();
    expect(screen.getByText("Reviewing the implementation plan")).toBeInTheDocument();
    expect(screen.getAllByText("Deal Finder").length).toBeGreaterThan(0);
    expect(apiMocks.getExecutionPlan).not.toHaveBeenCalled();
    await act(async () => {
      screen.getAllByRole("button", { name: "Apply Plan" })[0].click();
    });
    await waitFor(() => expect(apiMocks.applyApplicationPlan).toHaveBeenCalledWith("plan-1"));
    await waitFor(() =>
      expect(onOpenPanel).toHaveBeenCalledWith({
        key: "composer_detail",
        params: { workspace_id: "ws-1", application_plan_id: "plan-1", application_id: "app-1" },
      })
    );
  });

  it("disables no-op composer focus actions and points blocked threads to work-item review", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "thread_focus",
      context: {
        application_id: "app-1",
        goal_id: "goal-1",
        thread_id: "thread-1",
      },
      factory_catalog: [],
      application_plans: [],
      applications: [],
      application: {
        id: "app-1",
        name: "Lunch Poll",
        status: "active",
        source_factory_key: "lunch_poll",
        summary: "Lunch polling app",
        goal_count: 2,
        goals: [],
      },
      goal: {
        id: "goal-1",
        application_id: "app-1",
        title: "Workflow and Stabilization",
        planning_status: "ready",
        goal_progress_status: "active",
        thread_count: 1,
        threads: [],
        work_items: [],
      },
      thread: {
        id: "thread-1",
        workspace_id: "ws-1",
        goal_id: "goal-1",
        title: "Verification and Smoke Test",
        description: "",
        owner: null,
        priority: "high",
        status: "active",
        domain: "development",
        work_in_progress_limit: 1,
        execution_policy: { max_concurrent_runs: 1 },
        source_conversation_id: "thread-conversation-1",
        queued_work_items: 0,
        running_work_items: 0,
        awaiting_review_work_items: 1,
        completed_work_items: 0,
        failed_work_items: 0,
        recent_run_ids: [],
        work_items_completed: 0,
        work_items_blocked: 1,
        thread_diagnostic: {
          status: "blocked",
          observations: ["Execution brief review is still blocking coding dispatch for this thread."],
          likely_causes: [],
          evidence: [],
          provenance: { summary: "Execution brief review is required before coding execution can proceed." },
          suggested_human_review_action: "Review the blocking execution brief and approve it before dispatch.",
        },
      },
      related_goals: [
        {
          id: "goal-1",
          application_id: "app-1",
          title: "Workflow and Stabilization",
          planning_status: "ready",
          goal_progress_status: "active",
          thread_count: 1,
        },
      ],
      related_threads: [
        {
          id: "thread-1",
          workspace_id: "ws-1",
          goal_id: "goal-1",
          title: "Verification and Smoke Test",
          description: "",
          owner: null,
          priority: "high",
          status: "active",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: { max_concurrent_runs: 1 },
          source_conversation_id: "thread-conversation-1",
          queued_work_items: 0,
          running_work_items: 0,
          awaiting_review_work_items: 1,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
        },
      ],
      breadcrumbs: [
        { kind: "composer", label: "Composer" },
        { kind: "application", label: "Lunch Poll", id: "app-1" },
        { kind: "goal", label: "Workflow and Stabilization", id: "goal-1" },
        { kind: "thread", label: "Verification and Smoke Test", id: "thread-1" },
      ],
      available_actions: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "composer",
            panel_type: "detail",
            instance_key: "composer:ws-1",
            key: "composer_detail",
            params: { workspace_id: "ws-1", application_id: "app-1", goal_id: "goal-1", thread_id: "thread-1" },
          }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText("Review Required Before Resuming")).toBeInTheDocument());
    expect(screen.getByText("Waiting on a fix or input")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Current Goal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Current Thread" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Resume Thread" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Queue Next Slice" })).toBeDisabled();
    expect(screen.getByText("Review Required Before Resuming")).toBeInTheDocument();
    expect(screen.getAllByText(/review the blocking execution brief/i).length).toBeGreaterThan(0);

    await act(async () => {
      screen.getAllByRole("button", { name: "Review Work Items" })[0].click();
    });

    expect(onOpenPanel).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "thread_detail",
        params: { thread_id: "thread-1" },
      })
    );
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
            source: "coordination_event",
            work_item_id: "wi-1",
            work_item_title: "Implement scheduler",
            run_id: "run-1",
            status: "queued",
            summary: "Promoted for queue dispatch",
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
      thread_diagnostic: {
        status: "active",
        observations: ["Runtime refactor is progressing but still depends on the current queue slice."],
        likely_causes: ["The thread still has active in-flight work."],
        evidence: ["1 ready work item and 1 running work item remain in the thread."],
        suggested_human_review_action: "Review the next run result before queueing more work.",
        provenance: {
          provenance_status: "supervised_queue_proven",
          supervised_queue_evidence: true,
          ambiguous_runtime_evidence: false,
          evidence: ["A run_dispatched_from_queue event exists for the active run."],
          summary: "Recent execution is attributable to the supervised queue path.",
        },
      },
      metrics: {
        average_run_duration_seconds: 120,
        total_completed_work_items: 0,
        failed_work_items: 0,
        blocked_work_items: 0,
      },
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
          execution_brief_review: {
            has_brief: true,
            review_state: "approved",
            revision: 2,
            history_count: 1,
            summary: "Implement scheduler handoff",
            objective: "Keep the scheduler change scoped.",
            target_repository_slug: "xyn-platform",
            target_branch: "develop",
            gated: true,
            ready: true,
            blocked: false,
            blocked_reason: null,
            blocked_message: "Execution brief is ready for execution.",
            review_notes: "Approved for execution",
            available_actions: ["reject", "regenerate"],
          },
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
          source: "coordination_event",
          work_item_id: "wi-1",
          work_item_title: "Implement scheduler",
          run_id: "run-1",
          status: "queued",
          summary: "Promoted for queue dispatch",
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
    await waitFor(() => expect(screen.getAllByText("Implement scheduler").length).toBeGreaterThan(0));
    expect(screen.getByText("run_dispatched_from_queue")).toBeInTheDocument();
    expect(screen.getByText("coordination_event")).toBeInTheDocument();
    expect(screen.getByText("Promoted for queue dispatch")).toBeInTheDocument();
    expect(screen.getByText("Final summary")).toBeInTheDocument();
    expect(screen.getByText("Thread Review")).toBeInTheDocument();
    expect(screen.getByText("Thread Diagnostic")).toBeInTheDocument();
    expect(screen.getByText("Runtime refactor is progressing but still depends on the current queue slice.")).toBeInTheDocument();
    expect(screen.getByText("Avg Run Duration")).toBeInTheDocument();
    expect(screen.getByText("120s")).toBeInTheDocument();
    expect(screen.getByText("Scheduler refactor is running")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Execution brief is ready for execution.")).toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "Queue Next Slice" }).click();
    });

    await waitFor(() => expect(apiMocks.reviewCoordinationThread).toHaveBeenCalledWith("thread-1", "queue_next_slice"));
    expect(screen.getByText("Approved the next slice for Runtime Refactor.")).toBeInTheDocument();
  });

  it("loads runtime artifact content for runtime-backed artifact detail panels", async () => {
    apiMocks.getWorkItem.mockResolvedValue({
      id: "task-1",
      work_item_id: "wi-1",
      title: "Implement scheduler",
      description: "Use the stored brief instead of inferring intent.",
      status: "awaiting_review",
      target_repo: "xyn-platform",
      target_branch: "develop",
      task_type: "codegen",
      priority: 0,
      attempts: 0,
      max_attempts: 2,
      has_execution_brief: true,
      execution_brief_revision: 2,
      execution_brief_history_count: 1,
      execution_brief_review_state: "draft",
      execution_brief_review_notes: "Needs explicit approval",
      execution_queue: {
        queue_ready: false,
        dispatchable: false,
        dispatched: false,
        blocked: true,
        status: "blocked",
        reason: "brief_not_ready",
        message: "Execution brief review is required before coding execution can proceed.",
      },
      execution_brief_review: {
        has_brief: true,
        review_state: "draft",
        revision: 2,
        history_count: 1,
        summary: "Implement scheduler via the bounded handoff",
        objective: "Keep changes inside the scheduler seam.",
        target_repository_slug: "xyn-platform",
        target_branch: "develop",
        gated: true,
        ready: false,
        blocked: true,
        blocked_reason: "brief_not_ready",
        blocked_message: "Execution brief review is required before coding execution can proceed.",
        review_notes: "Needs explicit approval",
        available_actions: ["mark_ready", "approve", "reject", "regenerate"],
      },
      execution_run: {
        has_run: false,
        run_id: null,
        source: null,
        state: "not_started",
        raw_status: null,
        validation_status: "not_run",
        summary: null,
        error: null,
        started_at: null,
        finished_at: null,
        artifact_count: 0,
        artifact_labels: [],
        message: "No execution run has been dispatched yet.",
      },
      change_set: {
        available: true,
        status: "changed",
        has_changes: true,
        source: "workspace",
        repository_slug: "xyn-platform",
        changed_file_count: 2,
        files: [
          { path: "services/scheduler.py", change_type: "modified", patch_available: true },
          { path: "services/queue.py", change_type: "added", patch_available: true },
        ],
        patch_available: true,
        message: "2 files changed in the managed workspace.",
        diff_text: "diff --git a/services/scheduler.py b/services/scheduler.py\n@@ -1 +1 @@\n-old\n+new\n",
      },
      publish_state: {
        status: "idle",
        repository_slug: "xyn-platform",
        branch: "xyn/task/task-1",
        commit: null,
        push_status: null,
        message: "No publish action has been recorded yet.",
        available_actions: ["commit", "commit_and_push"],
      },
      execution_brief: {
        schema_version: "v1",
        revision: 2,
        summary: "Implement scheduler via the bounded handoff",
        objective: "Keep changes inside the scheduler seam.",
      },
      execution_brief_history: [{ revision: 1 }],
    });
    apiMocks.updateWorkItem.mockResolvedValue({
      id: "task-1",
      work_item_id: "wi-1",
      title: "Implement scheduler",
      description: "Use the stored brief instead of inferring intent.",
      status: "queued",
      target_repo: "xyn-platform",
      target_branch: "develop",
      task_type: "codegen",
      priority: 0,
      attempts: 0,
      max_attempts: 2,
      has_execution_brief: true,
      execution_brief_revision: 2,
      execution_brief_history_count: 1,
      execution_brief_review_state: "approved",
      execution_brief_review_notes: "Approved for coding",
      execution_queue: {
        queue_ready: true,
        dispatchable: true,
        dispatched: false,
        blocked: false,
        status: "queue_ready",
        reason: null,
        message: "Task is approved and ready for queue dispatch.",
      },
      execution_brief_review: {
        has_brief: true,
        review_state: "approved",
        revision: 2,
        history_count: 1,
        summary: "Implement scheduler via the bounded handoff",
        objective: "Keep changes inside the scheduler seam.",
        target_repository_slug: "xyn-platform",
        target_branch: "develop",
        gated: true,
        ready: true,
        blocked: false,
        blocked_reason: null,
        blocked_message: "Execution brief is ready for execution.",
        review_notes: "Approved for coding",
        available_actions: ["reject", "regenerate"],
      },
      execution_run: {
        has_run: false,
        run_id: null,
        source: null,
        state: "not_started",
        raw_status: null,
        validation_status: "not_run",
        summary: null,
        error: null,
        started_at: null,
        finished_at: null,
        artifact_count: 0,
        artifact_labels: [],
        message: "No execution run has been dispatched yet.",
      },
      change_set: {
        available: true,
        status: "changed",
        has_changes: true,
        source: "workspace",
        repository_slug: "xyn-platform",
        changed_file_count: 2,
        files: [
          { path: "services/scheduler.py", change_type: "modified", patch_available: true },
          { path: "services/queue.py", change_type: "added", patch_available: true },
        ],
        patch_available: true,
        message: "2 files changed in the managed workspace.",
        diff_text: "diff --git a/services/scheduler.py b/services/scheduler.py\n@@ -1 +1 @@\n-old\n+new\n",
      },
      publish_state: {
        status: "idle",
        repository_slug: "xyn-platform",
        branch: "xyn/task/task-1",
        commit: null,
        push_status: null,
        message: "No publish action has been recorded yet.",
        available_actions: ["commit", "commit_and_push"],
      },
      execution_brief: {
        schema_version: "v1",
        revision: 2,
        summary: "Implement scheduler via the bounded handoff",
        objective: "Keep changes inside the scheduler seam.",
      },
      execution_brief_history: [{ revision: 1 }],
    });
    apiMocks.dispatchWorkItem.mockResolvedValue({
      status: "dispatched",
      queue_item: { thread_id: "thread-1", work_item_id: "wi-1", task_id: "task-1" },
      run_id: "run-1",
      work_item: {
        id: "task-1",
        work_item_id: "wi-1",
        title: "Implement scheduler",
        description: "Use the stored brief instead of inferring intent.",
        status: "queued",
        target_repo: "xyn-platform",
        target_branch: "develop",
        runtime_run_id: "run-1",
        task_type: "codegen",
        priority: 0,
        attempts: 0,
        max_attempts: 2,
        has_execution_brief: true,
        execution_brief_revision: 2,
        execution_brief_history_count: 1,
        execution_brief_review_state: "approved",
        execution_brief_review_notes: "Approved for coding",
        execution_queue: {
          queue_ready: false,
          dispatchable: false,
          dispatched: true,
          blocked: false,
          status: "dispatched",
          reason: "in_flight",
          message: "Task has already been dispatched and is in progress.",
        },
        execution_brief_review: {
          has_brief: true,
          review_state: "approved",
          revision: 2,
          history_count: 1,
          summary: "Implement scheduler via the bounded handoff",
          objective: "Keep changes inside the scheduler seam.",
          target_repository_slug: "xyn-platform",
          target_branch: "develop",
          gated: true,
          ready: true,
          blocked: false,
          blocked_reason: null,
          blocked_message: "Execution brief is ready for execution.",
          review_notes: "Approved for coding",
          available_actions: ["reject", "regenerate"],
        },
        execution_run: {
          has_run: true,
          run_id: "run-1",
          source: "runtime",
          state: "queued",
          raw_status: "queued",
          validation_status: "pending",
          summary: null,
          error: null,
          started_at: null,
          finished_at: null,
          artifact_count: 0,
          artifact_labels: [],
          message: "Task has been dispatched and is waiting to start.",
        },
        change_set: {
          available: true,
          status: "changed",
          has_changes: true,
          source: "workspace",
          repository_slug: "xyn-platform",
          changed_file_count: 2,
          files: [
            { path: "services/scheduler.py", change_type: "modified", patch_available: true },
            { path: "services/queue.py", change_type: "added", patch_available: true },
          ],
          patch_available: true,
          message: "2 files changed in the managed workspace.",
          diff_text: "diff --git a/services/scheduler.py b/services/scheduler.py\n@@ -1 +1 @@\n-old\n+new\n",
        },
        publish_state: {
          status: "idle",
          repository_slug: "xyn-platform",
          branch: "xyn/task/task-1",
          commit: null,
          push_status: null,
          message: "No publish action has been recorded yet.",
          available_actions: ["commit", "commit_and_push"],
        },
        execution_brief: {
          schema_version: "v1",
          revision: 2,
          summary: "Implement scheduler via the bounded handoff",
          objective: "Keep changes inside the scheduler seam.",
        },
        execution_brief_history: [{ revision: 1 }],
      },
    });
    apiMocks.publishDevTask.mockResolvedValue({
      status: "pushed",
      push: true,
      work_item: {
        id: "task-1",
        work_item_id: "wi-1",
        title: "Implement scheduler",
        description: "Use the stored brief instead of inferring intent.",
        status: "queued",
        target_repo: "xyn-platform",
        target_branch: "develop",
        runtime_run_id: "run-1",
        task_type: "codegen",
        priority: 0,
        attempts: 0,
        max_attempts: 2,
        has_execution_brief: true,
        execution_brief_revision: 2,
        execution_brief_history_count: 1,
        execution_brief_review_state: "approved",
        execution_brief_review_notes: "Approved for coding",
        execution_queue: {
          queue_ready: true,
          dispatchable: true,
          dispatched: false,
          blocked: false,
          status: "ready",
          reason: "ready",
          message: "Task is approved and ready for queue dispatch.",
        },
        execution_brief_review: {
          has_brief: true,
          review_state: "approved",
          revision: 2,
          history_count: 1,
          summary: "Implement scheduler via the bounded handoff",
          objective: "Keep changes inside the scheduler seam.",
          target_repository_slug: "xyn-platform",
          target_branch: "develop",
          gated: true,
          ready: true,
          blocked: false,
          blocked_reason: null,
          blocked_message: "Execution brief is ready for execution.",
          review_notes: "Approved for coding",
          available_actions: ["reject", "regenerate"],
        },
        execution_run: {
          has_run: false,
          run_id: null,
          source: null,
          state: "not_run",
          raw_status: null,
          validation_status: null,
          summary: null,
          error: null,
          started_at: null,
          finished_at: null,
          artifact_count: 0,
          artifact_labels: [],
          message: "No execution run has been dispatched yet.",
        },
        change_set: {
          available: true,
          status: "changed",
          has_changes: true,
          source: "workspace",
          repository_slug: "xyn-platform",
          changed_file_count: 2,
          files: [
            { path: "services/scheduler.py", change_type: "modified", patch_available: true },
            { path: "services/queue.py", change_type: "added", patch_available: true },
          ],
          patch_available: true,
          message: "2 files changed in the managed workspace.",
          diff_text: "diff --git a/services/scheduler.py b/services/scheduler.py\n@@ -1 +1 @@\n-old\n+new\n",
        },
        publish_state: {
          status: "pushed",
          repository_slug: "xyn-platform",
          branch: "xyn/task/task-1",
          commit: "abc1234",
          push_status: "pushed",
          published_at: "2026-03-14T10:00:00Z",
          pushed_at: "2026-03-14T10:05:00Z",
          message: "Committed changes and pushed the task branch.",
          available_actions: [],
        },
        execution_brief: {
          schema_version: "v1",
          revision: 2,
          summary: "Implement scheduler via the bounded handoff",
          objective: "Keep changes inside the scheduler seam.",
        },
        execution_brief_history: [{ revision: 1 }],
      },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "work-item-detail", panel_type: "detail", instance_key: "work-item:task-1", key: "work_item_detail", params: { work_item_id: "task-1" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getWorkItem).toHaveBeenCalledWith("task-1"));
    expect(screen.getByText("Execution Queue")).toBeInTheDocument();
    expect(screen.getAllByText("Execution brief review is required before coding execution can proceed.").length).toBeGreaterThan(0);
    expect(screen.getByText("Execution Brief Review")).toBeInTheDocument();
    expect(screen.getByText("Execution Run")).toBeInTheDocument();
    expect(screen.getByText("Workspace Changes")).toBeInTheDocument();
    expect(screen.getByText("Publish")).toBeInTheDocument();
    expect(screen.getByText("Execution Blocked")).toBeInTheDocument();
    expect(screen.getByText("Implement scheduler via the bounded handoff")).toBeInTheDocument();
    expect(screen.getByText("No execution run has been dispatched yet.")).toBeInTheDocument();
    expect(screen.getByText("Not Run")).toBeInTheDocument();
    expect(screen.getByText("2 files changed in the managed workspace.")).toBeInTheDocument();
    expect(screen.getByText(/Modified: services\/scheduler\.py/)).toBeInTheDocument();
    expect(screen.getByText(/diff --git a\/services\/scheduler\.py b\/services\/scheduler\.py/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commit & Push" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Dispatch Task" })).not.toBeInTheDocument();

    await act(async () => {
      screen.getByRole("button", { name: "Approve" }).click();
    });

    await waitFor(() =>
      expect(apiMocks.updateWorkItem).toHaveBeenCalledWith("task-1", {
        execution_brief_action: "approve",
        execution_brief_revision_reason: undefined,
      }),
    );
    expect(screen.getByText("Task is approved and ready for queue dispatch.")).toBeInTheDocument();
    expect(screen.getByText("Queue Ready")).toBeInTheDocument();
    expect(screen.getByText("Execution Ready")).toBeInTheDocument();
    expect(screen.getByText("Execution brief is ready for execution.")).toBeInTheDocument();
    expect(screen.getByText("Execution brief Approve.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Dispatch Task" })).toBeEnabled();

    await act(async () => {
      screen.getByRole("button", { name: "Dispatch Task" }).click();
    });
    await waitFor(() => expect(apiMocks.dispatchWorkItem).toHaveBeenCalledWith("task-1", "ws-1"));
    expect(screen.getByText("Task has already been dispatched and is in progress.")).toBeInTheDocument();
    expect(screen.getByText("Dispatched wi-1.")).toBeInTheDocument();
    expect(screen.getByText("Latest execution run: run-1 · workspace ws-1")).toBeInTheDocument();
    expect(screen.getByText("Task has been dispatched and is waiting to start.")).toBeInTheDocument();
  });

  it("shows recovery state and supports retry and requeue from work item detail", async () => {
    apiMocks.getWorkItem.mockResolvedValueOnce({
      id: "task-2",
      work_item_id: "wi-2",
      title: "Recover failed scheduler task",
      description: "Retry after the last failed coding run.",
      status: "failed",
      target_repo: "xyn-platform",
      target_branch: "develop",
      runtime_run_id: "run-failed",
      task_type: "codegen",
      priority: 0,
      attempts: 1,
      max_attempts: 2,
      has_execution_brief: true,
      execution_brief_revision: 1,
      execution_brief_history_count: 0,
      execution_brief_review_state: "approved",
      execution_brief_review_notes: "Approved for retry",
      execution_queue: {
        queue_ready: false,
        dispatchable: false,
        dispatched: false,
        blocked: false,
        status: "terminal",
        reason: "status_failed",
        message: "Task is failed and is no longer dispatchable.",
      },
      execution_brief_review: {
        has_brief: true,
        review_state: "approved",
        revision: 1,
        history_count: 0,
        summary: "Recover failed scheduler task",
        objective: "Retry the failed coding work.",
        target_repository_slug: "xyn-platform",
        target_branch: "develop",
        gated: true,
        ready: true,
        blocked: false,
        blocked_reason: null,
        blocked_message: "Execution brief is ready for execution.",
        review_notes: "Approved for retry",
        available_actions: ["reject", "regenerate"],
      },
      execution_run: {
        has_run: true,
        run_id: "run-failed",
        source: "runtime",
        state: "failed",
        raw_status: "failed",
        validation_status: "failed",
        summary: "Tests failed",
        error: "tests_failed",
        started_at: "2026-03-14T12:00:00Z",
        finished_at: "2026-03-14T12:05:00Z",
        artifact_count: 1,
        artifact_labels: ["failure.log"],
        message: "Tests failed",
      },
      execution_recovery: {
        retryable: true,
        requeueable: true,
        in_flight: false,
        failed: true,
        blocked: false,
        status: "retryable",
        reason: null,
        message: "Execution failed and can be retried now or returned to the queue.",
        available_actions: ["retry_now", "requeue"],
        last_failure: {
          run_id: "run-failed",
          source: "runtime",
          state: "failed",
          summary: "Tests failed",
          error: "tests_failed",
          finished_at: "2026-03-14T12:05:00Z",
          recorded_at: "2026-03-14T12:05:01Z",
          action: null,
        },
      },
    });
    apiMocks.retryDevTask.mockResolvedValue({
      status: "queued",
      run_id: "run-retry",
      work_item: {
        id: "task-2",
        work_item_id: "wi-2",
        title: "Recover failed scheduler task",
        description: "Retry after the last failed coding run.",
        status: "queued",
        target_repo: "xyn-platform",
        target_branch: "develop",
        runtime_run_id: "run-retry",
        task_type: "codegen",
        priority: 0,
        attempts: 1,
        max_attempts: 2,
        execution_queue: {
          queue_ready: false,
          dispatchable: false,
          dispatched: true,
          blocked: false,
          status: "dispatched",
          reason: "in_flight",
          message: "Task has already been dispatched and is in progress.",
        },
        execution_run: {
          has_run: true,
          run_id: "run-retry",
          source: "runtime",
          state: "queued",
          raw_status: "queued",
          validation_status: "pending",
          summary: null,
          error: null,
          started_at: null,
          finished_at: null,
          artifact_count: 0,
          artifact_labels: [],
          message: "Task has been dispatched and is waiting to start.",
        },
        execution_recovery: {
          retryable: false,
          requeueable: false,
          in_flight: true,
          failed: false,
          blocked: true,
          status: "in_flight",
          reason: "in_flight",
          message: "Execution is already in progress and cannot be retried or requeued.",
          available_actions: [],
          last_failure: {
            run_id: "run-failed",
            source: "runtime",
            state: "failed",
            summary: "Tests failed",
            error: "tests_failed",
            finished_at: "2026-03-14T12:05:00Z",
            recorded_at: "2026-03-14T12:05:01Z",
            action: "retry",
          },
        },
      },
    });
    apiMocks.requeueDevTask.mockResolvedValue({
      status: "queued",
      work_item: {
        id: "task-2",
        work_item_id: "wi-2",
        title: "Recover failed scheduler task",
        description: "Retry after the last failed coding run.",
        status: "queued",
        target_repo: "xyn-platform",
        target_branch: "develop",
        task_type: "codegen",
        priority: 0,
        attempts: 1,
        max_attempts: 2,
        execution_queue: {
          queue_ready: true,
          dispatchable: true,
          dispatched: false,
          blocked: false,
          status: "queue_ready",
          reason: null,
          message: "Task is approved and ready for queue dispatch.",
        },
        execution_run: {
          has_run: false,
          run_id: null,
          source: null,
          state: "not_started",
          raw_status: null,
          validation_status: "not_run",
          summary: null,
          error: null,
          started_at: null,
          finished_at: null,
          artifact_count: 0,
          artifact_labels: [],
          message: "No execution run has been dispatched yet.",
        },
        execution_recovery: {
          retryable: false,
          requeueable: false,
          in_flight: false,
          failed: false,
          blocked: false,
          status: "requeued",
          reason: "requeued",
          message: "Task has been returned to the execution queue after a failed run.",
          available_actions: [],
          last_failure: {
            run_id: "run-failed",
            source: "runtime",
            state: "failed",
            summary: "Tests failed",
            error: "tests_failed",
            finished_at: "2026-03-14T12:05:00Z",
            recorded_at: "2026-03-14T12:05:01Z",
            action: "requeue",
          },
        },
      },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "work-item-detail-recovery", panel_type: "detail", instance_key: "work-item:task-2", key: "work_item_detail", params: { work_item_id: "task-2" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getWorkItem).toHaveBeenCalledWith("task-2"));
    expect(screen.getByText("Recovery")).toBeInTheDocument();
    expect(screen.getByText("Execution failed and can be retried now or returned to the queue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry Now" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Requeue" })).toBeEnabled();

    await act(async () => {
      screen.getByRole("button", { name: "Retry Now" }).click();
    });
    await waitFor(() => expect(apiMocks.retryDevTask).toHaveBeenCalledWith("task-2"));
    expect(screen.getByText("Retried wi-2 as run run-retry.")).toBeInTheDocument();
    expect(screen.getByText("Execution is already in progress and cannot be retried or requeued.")).toBeInTheDocument();

    apiMocks.getWorkItem.mockResolvedValueOnce({
      id: "task-2",
      work_item_id: "wi-2",
      title: "Recover failed scheduler task",
      description: "Retry after the last failed coding run.",
      status: "failed",
      target_repo: "xyn-platform",
      target_branch: "develop",
      task_type: "codegen",
      priority: 0,
      attempts: 1,
      max_attempts: 2,
      execution_queue: {
        queue_ready: false,
        dispatchable: false,
        dispatched: false,
        blocked: false,
        status: "terminal",
        reason: "status_failed",
        message: "Task is failed and is no longer dispatchable.",
      },
      execution_run: {
        has_run: true,
        run_id: "run-failed",
        source: "runtime",
        state: "failed",
        raw_status: "failed",
        validation_status: "failed",
        summary: "Tests failed",
        error: "tests_failed",
        started_at: "2026-03-14T12:00:00Z",
        finished_at: "2026-03-14T12:05:00Z",
        artifact_count: 1,
        artifact_labels: ["failure.log"],
        message: "Tests failed",
      },
      execution_recovery: {
        retryable: true,
        requeueable: true,
        in_flight: false,
        failed: true,
        blocked: false,
        status: "retryable",
        reason: null,
        message: "Execution failed and can be retried now or returned to the queue.",
        available_actions: ["retry_now", "requeue"],
        last_failure: {
          run_id: "run-failed",
          source: "runtime",
          state: "failed",
          summary: "Tests failed",
          error: "tests_failed",
          finished_at: "2026-03-14T12:05:00Z",
          recorded_at: "2026-03-14T12:05:01Z",
          action: null,
        },
      },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "work-item-detail-requeue", panel_type: "detail", instance_key: "work-item:task-2-requeue", key: "work_item_detail", params: { work_item_id: "task-2" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getWorkItem).toHaveBeenCalledWith("task-2"));
    await act(async () => {
      const buttons = screen.getAllByRole("button", { name: "Requeue" });
      buttons[buttons.length - 1].click();
    });
    await waitFor(() => expect(apiMocks.requeueDevTask).toHaveBeenCalledWith("task-2"));
    expect(screen.getByText("Returned wi-2 to the queue.")).toBeInTheDocument();
    expect(screen.getByText("Task has been returned to the execution queue after a failed run.")).toBeInTheDocument();
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
      analysis: {
        artifact_identity: "final_summary.md",
        version_count: 2,
        recent_activity_count: 2,
        status: "stable_progression",
        observations: ["Artifact history shows steady progression without repeated failed revisions."],
        evidence: ["2 revision(s) are present without repeated failure-linked churn."],
        suggested_human_review_focus: "Continue reviewing later revisions for substantive changes.",
        provenance: {
          provenance_status: "supervised_queue_proven",
          supervised_queue_evidence: true,
          ambiguous_runtime_evidence: false,
          evidence: ["At least one artifact revision is linked to an explicit supervised queue dispatch event."],
          summary: "Supervised queue provenance is proven for at least part of this artifact history.",
        },
      },
      evolution: [
        {
          artifact_id: "artifact-older",
          run_id: "run-0",
          work_item_id: "wi-1",
          artifact_type: "summary",
          label: "final_summary.md",
          uri: "artifact://runs/run-0/final_summary.md",
          created_at: "2026-03-12T10:00:00Z",
          is_current: false,
        },
        {
          artifact_id: "artifact-1",
          run_id: "run-1",
          work_item_id: "wi-1",
          artifact_type: "summary",
          label: "final_summary.md",
          uri: "artifact://runs/run-1/final_summary.md",
          created_at: "2026-03-12T10:10:00Z",
          is_current: true,
        },
      ],
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
    expect(screen.getByText("Artifact Evolution")).toBeInTheDocument();
    expect(screen.getByText("Artifact Analysis")).toBeInTheDocument();
    expect(screen.getByText("stable_progression")).toBeInTheDocument();
    expect(screen.getByText("Supervised queue provenance is proven for at least part of this artifact history.")).toBeInTheDocument();
    expect(screen.getByText("run-0")).toBeInTheDocument();
    expect(screen.getByText("yes")).toBeInTheDocument();
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

  it("loads application plan detail and applies through the application API", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getApplicationPlan.mockResolvedValue({
      id: "plan-1",
      workspace_id: "ws-1",
      application_id: null,
      name: "Deal Finder",
      summary: "Reviewable application plan",
      source_factory_key: "ai_real_estate_deal_finder",
      source_conversation_id: "thread-1",
      requested_by: "user-1",
      status: "review",
      request_objective: "Build an AI real estate deal finder",
      plan_fingerprint: "fp-1",
      generated_goal_count: 2,
      created_at: "2026-03-13T10:00:00Z",
      updated_at: "2026-03-13T10:00:00Z",
      factory: {
        key: "ai_real_estate_deal_finder",
        name: "AI Real Estate Deal Finder",
        description: "Builds a real estate opportunity workflow.",
        intended_use_case: "Property discovery and scoring",
        generated_goal_families: ["foundation", "analysis"],
        assumptions: ["MVP first"],
      },
      application_name: "Deal Finder",
      application_summary: "A real estate deal finder",
      ordering_hints: ["Start with ingestion."],
      dependency_hints: ["Scoring depends on comps."],
      resolution_notes: ["Review before apply."],
      generated_goals: [
        {
          title: "Listing and Property Foundation",
          description: "Build the first slice",
          priority: "high",
          goal_type: "build_system",
          planning_summary: "Start with durable entities.",
          resolution_notes: [],
          threads: [],
          work_items: [],
        },
      ],
      generated_plan: {
        application_name: "Deal Finder",
        application_summary: "A real estate deal finder",
        source_factory_key: "ai_real_estate_deal_finder",
        request_objective: "Build an AI real estate deal finder",
        ordering_hints: ["Start with ingestion."],
        dependency_hints: ["Scoring depends on comps."],
        resolution_notes: ["Review before apply."],
        generated_goals: [
          {
            title: "Listing and Property Foundation",
            description: "Build the first slice",
            priority: "high",
            goal_type: "build_system",
            planning_summary: "Start with durable entities.",
            resolution_notes: [],
            threads: [],
            work_items: [],
          },
        ],
      },
    });
    apiMocks.applyApplicationPlan.mockResolvedValue({
      status: "applied",
      application: {
        id: "app-1",
        workspace_id: "ws-1",
        name: "Deal Finder",
        summary: "A real estate deal finder",
        source_factory_key: "ai_real_estate_deal_finder",
        source_conversation_id: "thread-1",
        requested_by: "user-1",
        status: "active",
        request_objective: "Build an AI real estate deal finder",
        goal_count: 1,
        portfolio_state: { goals: [], insights: [], recommended_goal: null },
        created_at: "2026-03-13T10:00:00Z",
        updated_at: "2026-03-13T10:05:00Z",
        factory: null,
        goals: [],
        metadata: {},
      },
      application_plan: { id: "plan-1" },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "plan-1", panel_type: "detail", instance_key: "application_plan:plan-1", key: "application_plan_detail", params: { application_plan_id: "plan-1" } }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getApplicationPlan).toHaveBeenCalledWith("plan-1"));
    await waitFor(() => expect(screen.getByText("Reviewable application plan")).toBeInTheDocument());
    await act(async () => {
      screen.getByRole("button", { name: "Apply Plan" }).click();
    });
    await waitFor(() => expect(apiMocks.applyApplicationPlan).toHaveBeenCalledWith("plan-1"));
    await waitFor(() =>
      expect(onOpenPanel).toHaveBeenCalledWith(
        expect.objectContaining({
          key: "application_detail",
          params: { application_id: "app-1" },
        }),
      ),
    );
  });

  it("loads application detail with grouped goals and portfolio summary", async () => {
    apiMocks.getApplication.mockResolvedValue({
      id: "app-1",
      workspace_id: "ws-1",
      name: "Deal Finder",
      summary: "A real estate deal finder",
      source_factory_key: "ai_real_estate_deal_finder",
      source_conversation_id: "thread-1",
      requested_by: "user-1",
      status: "active",
      request_objective: "Build an AI real estate deal finder",
      goal_count: 1,
      portfolio_state: {
        goals: [
          {
            goal_id: "goal-1",
            title: "Listing and Property Foundation",
            planning_status: "decomposed",
            goal_progress_status: "in_progress",
            progress_percent: 25,
            health_status: "active",
            active_threads: 1,
            blocked_threads: 0,
            recent_execution_count: 1,
            coordination_priority: { value: "medium", reasons: ["queueable work exists"] },
          },
        ],
        insights: [
          {
            key: "steady_progress",
            summary: "Portfolio activity is balanced around Listing and Property Foundation.",
            evidence: ["1 active thread exists."],
            goal_ids: ["goal-1"],
          },
        ],
        recommended_goal: null,
      },
      created_at: "2026-03-13T10:00:00Z",
      updated_at: "2026-03-13T10:05:00Z",
      factory: {
        key: "ai_real_estate_deal_finder",
        name: "AI Real Estate Deal Finder",
        description: "Builds a real estate opportunity workflow.",
        intended_use_case: "Property discovery and scoring",
        generated_goal_families: ["foundation"],
        assumptions: ["MVP first"],
      },
      goals: [
        {
          id: "goal-1",
          workspace_id: "ws-1",
          application_id: "app-1",
          title: "Listing and Property Foundation",
          description: "Build the first slice",
          goal_type: "build_system",
          planning_status: "decomposed",
          priority: "high",
          planning_summary: "Start with durable entities.",
          resolution_notes: [],
          thread_count: 1,
          work_item_count: 2,
          created_at: "2026-03-13T10:00:00Z",
          updated_at: "2026-03-13T10:00:00Z",
        },
      ],
      metadata: {},
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "app-1", panel_type: "detail", instance_key: "application:app-1", key: "application_detail", params: { application_id: "app-1" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(apiMocks.getApplication).toHaveBeenCalledWith("app-1"));
    await waitFor(() => expect(screen.getByText("Application")).toBeInTheDocument());
    expect(screen.getAllByText("Deal Finder").length).toBeGreaterThan(0);
    expect(screen.getByText("Listing and Property Foundation")).toBeInTheDocument();
    expect(screen.getByText("Active Goals")).toBeInTheDocument();
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

  it("loads composer discovery state with factory catalog", async () => {
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "factory_discovery",
      context: {
        factory_key: null,
        application_plan_id: null,
        application_id: null,
        goal_id: null,
        thread_id: null,
      },
      factory_catalog: [
        {
          key: "ai_real_estate_deal_finder",
          name: "AI Real Estate Deal Finder",
          description: "Plans a real estate deal finder MVP.",
          use_case: "real_estate",
          generated_goal_families: ["listing_ingestion", "deal_scoring"],
          assumptions: ["Bias toward MVP-first slices."],
        },
      ],
      selected_factory: null,
      application_plans: [],
      applications: [],
      application_plan: null,
      application: null,
      goal: null,
      thread: null,
      related_goals: [],
      related_threads: [],
      portfolio_context: null,
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{ panel_id: "composer-1", panel_type: "detail", instance_key: "composer:ws-1", key: "composer_detail", params: { workspace_id: "ws-1" } }}
          onOpenPanel={() => {}}
        />
      </MemoryRouter>
    );

    await waitFor(() =>
      expect(apiMocks.getComposerState).toHaveBeenCalledWith({
        workspace_id: "ws-1",
        factory_key: undefined,
        application_plan_id: undefined,
        application_id: undefined,
        goal_id: undefined,
        thread_id: undefined,
      })
    );
    expect(apiMocks.getExecutionPlan).not.toHaveBeenCalled();
    expect(screen.getByText("Application Efforts")).toBeInTheDocument();
    expect(screen.getByText("AI Real Estate Deal Finder")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Composer" })).not.toBeInTheDocument();
  });

  it("loads composer plan review state and applies plans through the existing apply seam", async () => {
    const onOpenPanel = vi.fn();
    apiMocks.getComposerState.mockResolvedValue({
      workspace_id: "ws-1",
      stage: "plan_review",
      context: {
        factory_key: "ai_real_estate_deal_finder",
        application_plan_id: "plan-1",
        application_id: null,
        goal_id: null,
        thread_id: null,
      },
      factory_catalog: [],
      selected_factory: {
        key: "ai_real_estate_deal_finder",
        name: "AI Real Estate Deal Finder",
        description: "Plans a real estate deal finder MVP.",
        use_case: "real_estate",
        generated_goal_families: ["listing_ingestion"],
        assumptions: ["Bias toward MVP-first slices."],
      },
      application_plans: [],
      applications: [],
      application_plan: {
        id: "plan-1",
        name: "Deal Finder",
        summary: "A reviewable MVP plan.",
        status: "review",
        source_factory_key: "ai_real_estate_deal_finder",
        generated_goals: [{ title: "Listing and Property Foundation" }],
        generated_threads: [],
        generated_work_items: [],
        resolution_notes: [],
        planning_output: { goal_count: 1 },
      },
      application: null,
      goal: null,
      thread: null,
      related_goals: [],
      related_threads: [],
      portfolio_context: null,
      breadcrumbs: [
        { kind: "composer", label: "Composer" },
        { kind: "factory", label: "AI Real Estate Deal Finder", id: "ai_real_estate_deal_finder" },
        { kind: "application_plan", label: "Deal Finder", id: "plan-1" },
      ],
      available_actions: [{ action_type: "apply_plan", label: "Apply Plan", enabled: true, target_kind: "application_plan", target_id: "plan-1" }],
    });
    apiMocks.applyApplicationPlan.mockResolvedValue({
      status: "applied",
      application: { id: "app-1", name: "Deal Finder" },
      application_plan: { id: "plan-1" },
    });

    render(
      <MemoryRouter>
        <WorkbenchPanelHost
          workspaceId="ws-1"
          panel={{
            panel_id: "composer-1",
            panel_type: "detail",
            instance_key: "composer:ws-1",
            key: "composer_detail",
            params: { workspace_id: "ws-1", application_plan_id: "plan-1", factory_key: "ai_real_estate_deal_finder" },
          }}
          onOpenPanel={onOpenPanel}
        />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getAllByText("Deal Finder").length).toBeGreaterThan(0));
    expect(screen.getByText("Selected Application Plan")).toBeInTheDocument();
    expect(screen.getAllByText("Deal Finder").length).toBeGreaterThan(0);
    await act(async () => {
      screen.getAllByRole("button", { name: /apply plan/i })[0].click();
    });
    await waitFor(() => expect(apiMocks.applyApplicationPlan).toHaveBeenCalledWith("plan-1"));
    expect(onOpenPanel).toHaveBeenCalledWith(
      expect.objectContaining({
        key: "composer_detail",
        params: expect.objectContaining({
          workspace_id: "ws-1",
          application_plan_id: "plan-1",
          application_id: "app-1",
        }),
      })
    );
  });
});
