import { describe, expect, it } from "vitest";

import type { ComposerState } from "../../../api/types";
import { deriveComposerStageSummary, deriveComposerViewModel } from "./composerViewModel";

describe("deriveComposerViewModel", () => {
  it("groups goals and threads under their application and isolates orphaned work", () => {
    const payload: ComposerState = {
      workspace_id: "ws-1",
      stage: "application_overview",
      context: {
        application_id: "app-2",
        goal_id: null,
        thread_id: null,
        application_plan_id: null,
        factory_key: null,
      },
      factory_catalog: [],
      selected_factory: null,
      application_plans: [
        {
          id: "plan-1",
          application_id: null,
          workspace_id: "ws-1",
          name: "Knowledgebase Plan",
          summary: "Reviewable plan",
          source_factory_key: "generic_application_mvp",
          source_conversation_id: "conv-2",
          requested_by: "user-1",
          status: "review",
          request_objective: "Build a personal knowledgebase",
          plan_fingerprint: "fp-1",
          created_at: "2026-03-16T15:00:00Z",
          updated_at: "2026-03-16T15:00:00Z",
        },
      ],
      applications: [
        {
          id: "app-1",
          workspace_id: "ws-1",
          name: "Lunch Poll",
          summary: "Failed lunch app effort",
          source_factory_key: "generic_application_mvp",
          source_conversation_id: "conv-1",
          requested_by: "user-1",
          status: "active",
          request_objective: "Build a lunch poll app",
          goal_count: 1,
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T11:00:00Z",
        },
        {
          id: "app-2",
          workspace_id: "ws-1",
          name: "Knowledgebase",
          summary: "Current app effort",
          source_factory_key: "generic_application_mvp",
          source_conversation_id: "conv-2",
          requested_by: "user-1",
          status: "active",
          request_objective: "Build a personal knowledgebase",
          goal_count: 1,
          created_at: "2026-03-16T10:00:00Z",
          updated_at: "2026-03-16T16:00:00Z",
        },
      ],
      application_plan: null,
      application: null,
      goal: null,
      thread: null,
      related_goals: [
        {
          id: "goal-1",
          workspace_id: "ws-1",
          application_id: "app-1",
          title: "Workflow and Stabilization",
          description: "",
          source_conversation_id: "conv-1",
          requested_by: "user-1",
          goal_type: "build_system",
          planning_status: "decomposed",
          priority: "high",
          planning_summary: "Repair the lunch app workflow.",
          resolution_notes: [],
          thread_count: 1,
          work_item_count: 2,
          goal_progress_status: "blocked",
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T11:05:00Z",
        },
        {
          id: "goal-2",
          workspace_id: "ws-1",
          application_id: "app-2",
          title: "Search and ingestion",
          description: "",
          source_conversation_id: "conv-2",
          requested_by: "user-1",
          goal_type: "build_system",
          planning_status: "decomposed",
          priority: "high",
          planning_summary: "Create the current knowledgebase flow.",
          resolution_notes: [],
          thread_count: 1,
          work_item_count: 1,
          goal_progress_status: "active",
          created_at: "2026-03-16T10:05:00Z",
          updated_at: "2026-03-16T16:05:00Z",
        },
        {
          id: "goal-orphan",
          workspace_id: "ws-1",
          application_id: null,
          title: "Legacy cleanup",
          description: "",
          source_conversation_id: "conv-0",
          requested_by: "user-1",
          goal_type: "stabilize_system",
          planning_status: "decomposed",
          priority: "normal",
          planning_summary: "Unlinked legacy work.",
          resolution_notes: [],
          thread_count: 1,
          work_item_count: 1,
          goal_progress_status: "active",
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
          created_at: "2026-03-15T11:00:00Z",
          updated_at: "2026-03-15T11:06:00Z",
        },
        {
          id: "thread-2",
          workspace_id: "ws-1",
          goal_id: "goal-2",
          goal_title: "Search and ingestion",
          title: "Ingestion slice",
          description: "",
          owner: null,
          priority: "high",
          status: "queued",
          domain: "development",
          work_in_progress_limit: 1,
          execution_policy: {},
          source_conversation_id: "conv-2",
          queued_work_items: 1,
          running_work_items: 0,
          awaiting_review_work_items: 0,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-16T16:00:00Z",
          updated_at: "2026-03-16T16:06:00Z",
        },
        {
          id: "thread-orphan",
          workspace_id: "ws-1",
          goal_id: "goal-orphan",
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
          created_at: "2026-03-14T10:05:00Z",
          updated_at: "2026-03-14T10:11:00Z",
        },
      ],
      portfolio_context: null,
      breadcrumbs: [{ kind: "composer", label: "Composer" }],
      available_actions: [],
    };

    const viewModel = deriveComposerViewModel(payload);

    expect(viewModel.containers.map((container) => container.title)).toEqual([
      "Knowledgebase",
      "Knowledgebase Plan",
      "Lunch Poll",
    ]);
    expect(viewModel.currentContext.container?.title).toBe("Knowledgebase");
    expect(viewModel.currentContext.container?.recencyLabel).toBe("Current");
    expect(viewModel.containers.find((container) => container.title === "Lunch Poll")?.goals[0]?.title).toBe("Workflow and Stabilization");
    expect(viewModel.containers.find((container) => container.title === "Lunch Poll")?.threads[0]?.title).toBe("Smoke test");
    expect(viewModel.unlinkedGoals.map((goal) => goal.title)).toEqual(["Legacy cleanup"]);
    expect(viewModel.unlinkedThreads.map((thread) => thread.title)).toEqual(["Cleanup slice"]);
  });
});

describe("deriveComposerStageSummary", () => {
  it("maps representative composer stages to human-readable workflow copy", () => {
    const base: ComposerState = {
      workspace_id: "ws-1",
      stage: "factory_discovery",
      context: {
        application_id: null,
        goal_id: null,
        thread_id: null,
        application_plan_id: null,
        factory_key: null,
      },
      factory_catalog: [],
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
    };

    const neutral = deriveComposerStageSummary(base, {
      title: "No application effort selected",
      statusLabel: "Idle",
      latestResult: "Start by selecting an application effort or generating a new plan.",
      latestActivityAt: null,
      container: null,
    });
    expect(neutral.label).toBe("No active build in progress");
    expect(neutral.nextStep).toBe("Start a new application plan.");

    const planReview = deriveComposerStageSummary(
      {
        ...base,
        stage: "plan_review",
        application_plan: {
          id: "plan-1",
          name: "Deal Finder",
          summary: "Reviewable plan",
          status: "review",
          source_factory_key: "generic_application_mvp",
          generated_goals: [{ title: "Goal 1" }, { title: "Goal 2" }],
        },
      } as unknown as ComposerState,
      {
        title: "Deal Finder",
        statusLabel: "Ready for review",
        latestResult: "2 planned goals ready to apply.",
        latestActivityAt: null,
        container: null,
      },
    );
    expect(planReview.label).toBe("Reviewing the implementation plan");
    expect(planReview.explanation).toMatch(/2 planned goals/i);

    const threadFocus = deriveComposerStageSummary(
      {
        ...base,
        stage: "thread_focus",
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
          source_conversation_id: "conv-1",
          queued_work_items: 0,
          running_work_items: 0,
          awaiting_review_work_items: 1,
          completed_work_items: 0,
          failed_work_items: 0,
          recent_run_ids: [],
          created_at: "2026-03-16T16:00:00Z",
          updated_at: "2026-03-16T16:01:00Z",
          thread_diagnostic: {
            status: "blocked",
            observations: ["Execution brief review is still blocking coding dispatch for this thread."],
            likely_causes: [],
            evidence: [],
            provenance: { summary: "Execution brief review is required before coding execution can proceed." },
            suggested_human_review_action: "Review the blocking work item.",
          },
        },
      } as unknown as ComposerState,
      {
        title: "Verification and Smoke Test",
        statusLabel: "Active",
        latestResult: "Execution brief review is required before coding execution can proceed.",
        latestActivityAt: null,
        container: null,
      },
    );
    expect(threadFocus.label).toBe("Waiting on a fix or input");
    expect(threadFocus.nextStep).toMatch(/review the blocking work item/i);
  });
});
