import type {
  ComposerStage,
  ApplicationPlanDetail,
  ApplicationPlanSummary,
  ApplicationSummary,
  ComposerState,
  CoordinationThreadSummary,
  GoalSummary,
} from "../../../api/types";

export type ComposerContainerKind = "application" | "application_plan";

export type ComposerContainerGoal = GoalSummary & {
  threads: CoordinationThreadSummary[];
};

export type ComposerWorkContainer = {
  kind: ComposerContainerKind;
  id: string;
  title: string;
  summary: string;
  promptSummary: string;
  statusLabel: string;
  recencyLabel: string;
  latestActivityAt: string | null;
  latestResult: string;
  isCurrent: boolean;
  isMostRecent: boolean;
  goals: ComposerContainerGoal[];
  threads: CoordinationThreadSummary[];
  goalCount: number;
  threadCount: number;
  selectionParams: Record<string, string>;
};

export type ComposerCurrentContext = {
  title: string;
  statusLabel: string;
  latestResult: string;
  latestActivityAt: string | null;
  container: ComposerWorkContainer | null;
};

export type ComposerViewModel = {
  containers: ComposerWorkContainer[];
  currentContext: ComposerCurrentContext;
  unlinkedGoals: GoalSummary[];
  unlinkedThreads: CoordinationThreadSummary[];
};

export type ComposerStageSummary = {
  label: string;
  explanation: string;
  nextStep: string;
};

function parseTimestamp(value?: string | null): number {
  const parsed = Date.parse(String(value || ""));
  return Number.isFinite(parsed) ? parsed : 0;
}

function latestTimestamp(values: Array<string | null | undefined>): string | null {
  let best: string | null = null;
  let bestTs = 0;
  for (const value of values) {
    const ts = parseTimestamp(value);
    if (ts > bestTs) {
      bestTs = ts;
      best = value ? String(value) : null;
    }
  }
  return best;
}

function statusLabelForApplication(application: ApplicationSummary, goals: GoalSummary[], threads: CoordinationThreadSummary[]): string {
  const blockedThreadCount = threads.filter((thread) => ["blocked", "failed"].includes(String(thread.status || "").toLowerCase())).length;
  const reviewBlockedCount = threads.reduce((sum, thread) => sum + Number(thread.awaiting_review_work_items || 0), 0);
  if (String(application.status || "").toLowerCase() === "archived") return "Archived";
  if (String(application.status || "").toLowerCase() === "completed") return "Completed";
  if (blockedThreadCount > 0 || reviewBlockedCount > 0) return "Needs attention";
  if (threads.some((thread) => String(thread.status || "").toLowerCase() === "active")) return "Active";
  if (goals.length > 0) return "Planned";
  return "Defined";
}

function latestResultForApplication(application: ApplicationSummary, goals: GoalSummary[], threads: CoordinationThreadSummary[]): string {
  const reviewBlockedCount = threads.reduce((sum, thread) => sum + Number(thread.awaiting_review_work_items || 0), 0);
  const failedThreadCount = threads.filter((thread) => ["failed", "blocked"].includes(String(thread.status || "").toLowerCase())).length;
  if (reviewBlockedCount > 0) {
    return `${reviewBlockedCount} work item${reviewBlockedCount === 1 ? "" : "s"} waiting for review before coding can continue.`;
  }
  if (failedThreadCount > 0) {
    return `${failedThreadCount} thread${failedThreadCount === 1 ? "" : "s"} blocked or failed.`;
  }
  const recommendedGoal = application.portfolio_state?.recommended_goal?.title;
  if (recommendedGoal) {
    return `Recommended goal: ${recommendedGoal}.`;
  }
  if (threads.some((thread) => thread.running_work_items > 0)) {
    return "Coding work is currently running.";
  }
  if (goals.length > 0) {
    return `${goals.length} goal${goals.length === 1 ? "" : "s"} available for review or dispatch.`;
  }
  return "No goal activity has started yet.";
}

function statusLabelForPlan(plan: ApplicationPlanSummary): string {
  const status = String(plan.status || "").toLowerCase();
  if (status === "applied") return "Applied";
  if (status === "canceled") return "Canceled";
  if (status === "review") return "Ready for review";
  return status ? status.replace(/[_-]+/g, " ") : "Draft";
}

function latestResultForPlan(plan: ApplicationPlanSummary, detail?: ApplicationPlanDetail | null): string {
  const goalCount = detail?.generated_goals?.length ?? detail?.generated_plan?.generated_goals?.length ?? 0;
  if (String(plan.status || "").toLowerCase() === "applied") {
    return "Plan has already been applied to a durable application.";
  }
  if (goalCount > 0) {
    return `${goalCount} planned goal${goalCount === 1 ? "" : "s"} ready to apply.`;
  }
  return "Plan is ready for review.";
}

function recencyLabel(isCurrent: boolean, isMostRecent: boolean): string {
  if (isCurrent) return "Current";
  if (isMostRecent) return "Most recent";
  return "Older";
}

function groupThreadsByGoal(threads: CoordinationThreadSummary[]): Map<string, CoordinationThreadSummary[]> {
  const grouped = new Map<string, CoordinationThreadSummary[]>();
  for (const thread of threads) {
    const goalId = String(thread.goal_id || "").trim();
    if (!goalId) continue;
    const current = grouped.get(goalId) || [];
    current.push(thread);
    grouped.set(goalId, current);
  }
  return grouped;
}

function mergeGoals(primary: GoalSummary[], secondary: GoalSummary[]): GoalSummary[] {
  const map = new Map<string, GoalSummary>();
  for (const goal of [...primary, ...secondary]) {
    map.set(goal.id, goal);
  }
  return Array.from(map.values());
}

export function deriveComposerStageSummary(payload: ComposerState, currentContext: ComposerCurrentContext): ComposerStageSummary {
  const stage = String(payload.stage || "").toLowerCase() as ComposerStage | "";
  const selectedFactory = payload.selected_factory;
  const selectedPlan = payload.application_plan;
  const selectedGoal = payload.goal;
  const selectedThread = payload.thread;
  const currentContainer = currentContext.container;
  const hasActiveEffort = Boolean(currentContainer || payload.applications?.length || payload.application_plans?.length);
  const goalCount = selectedPlan?.generated_goals?.length ?? selectedPlan?.generated_plan?.generated_goals?.length ?? 0;
  const reviewBlocked = Boolean(
    selectedThread?.awaiting_review_work_items
    || selectedThread?.thread_diagnostic?.suggested_human_review_action
    || selectedThread?.thread_diagnostic?.observations?.some((entry) => /review/i.test(String(entry || "")))
  );

  if (stage === "factory_discovery" && !selectedFactory && !hasActiveEffort) {
    return {
      label: "No active build in progress",
      explanation: "Composer is waiting for you to choose a starting template or describe a new application.",
      nextStep: "Start a new application plan.",
    };
  }

  switch (stage) {
    case "factory_discovery":
      return {
        label: "Choosing a starting template",
        explanation: selectedFactory
          ? `${selectedFactory.name} is selected as the starting point for the next application effort.`
          : "Composer is showing the available starting templates for a new application.",
        nextStep: "Choose the best template, then generate a plan.",
      };
    case "plan_review":
      return {
        label: "Reviewing the implementation plan",
        explanation: goalCount > 0
          ? `${goalCount} planned goal${goalCount === 1 ? "" : "s"} are ready to inspect before you apply the plan.`
          : "The plan is ready to inspect before it becomes a durable application effort.",
        nextStep: selectedPlan?.status === "applied" ? "Open the application effort." : "Apply the plan when it looks right.",
      };
    case "plan_applied":
      return {
        label: "Turning the plan into application work",
        explanation: "The reviewed plan has been attached to a durable application effort and is ready for follow-up work.",
        nextStep: "Open the application effort and review its goals.",
      };
    case "goal_focus":
      return {
        label: "Reviewing a goal",
        explanation: selectedGoal
          ? `${selectedGoal.title} is the current goal under ${currentContainer?.title || "this application effort"}.`
          : "Composer is focused on a specific goal so you can decide what to do next.",
        nextStep: "Review the recommendation, then approve the next slice if it looks correct.",
      };
    case "thread_focus":
      return {
        label: reviewBlocked ? "Waiting on a fix or input" : "Running work",
        explanation: reviewBlocked
          ? "The current thread is paused until a blocking review item is handled."
          : selectedThread
            ? `${selectedThread.title} is the active thread for this application effort.`
            : "Composer is focused on a specific thread.",
        nextStep: reviewBlocked ? "Review the blocking work item before queueing more work." : "Review the current thread and decide whether to continue dispatching work.",
      };
    case "application_overview":
      return {
        label: "Reviewing current application work",
        explanation: currentContainer
          ? `${currentContainer.title} is the active application effort in Composer.`
          : "Composer is summarizing the current application effort and its related work.",
        nextStep: "Choose the goal or thread you want to continue.",
      };
    default:
      return {
        label: "No active build in progress",
        explanation: "Composer is ready to organize application work when you select or start an effort.",
        nextStep: "Start a new application plan.",
      };
  }
}

export function deriveComposerViewModel(payload: ComposerState): ComposerViewModel {
  const selectedApplication = payload.application;
  const selectedPlan = payload.application_plan;
  const selectedGoal = payload.goal;
  const selectedThread = payload.thread;
  const selectedContainerKey = selectedApplication?.id
    ? `application:${selectedApplication.id}`
    : payload.context.application_id
      ? `application:${payload.context.application_id}`
      : selectedPlan?.id
        ? `application_plan:${selectedPlan.id}`
        : payload.context.application_plan_id
          ? `application_plan:${payload.context.application_plan_id}`
          : "";

  const threadsByGoal = groupThreadsByGoal(payload.related_threads || []);
  const appIds = new Set((payload.applications || []).map((application) => application.id));
  const selectedApplicationGoals = selectedApplication?.goals || [];
  const allRecentGoals = mergeGoals(payload.related_goals || [], selectedApplicationGoals);
  const goalsByApplication = new Map<string, GoalSummary[]>();

  for (const goal of allRecentGoals) {
    const applicationId = String(goal.application_id || "").trim();
    if (!applicationId) continue;
    const current = goalsByApplication.get(applicationId) || [];
    current.push(goal);
    goalsByApplication.set(applicationId, current);
  }

  // Composer groups work under real durable parents first: applied Applications,
  // then unapplied Application Plans. Goals/threads that cannot be attached stay
  // in the explicit unlinked bucket instead of floating as if they were global.
  const applicationRows = selectedApplication && !(payload.applications || []).some((application) => application.id === selectedApplication.id)
    ? [...(payload.applications || []), selectedApplication]
    : payload.applications || [];

  const applicationContainers: ComposerWorkContainer[] = applicationRows.map((application) => {
    const goals = goalsByApplication.get(application.id) || [];
    const threads = goals.flatMap((goal) => threadsByGoal.get(goal.id) || []);
    const latestActivityAt = latestTimestamp([
      application.updated_at,
      ...goals.map((goal) => goal.updated_at),
      ...threads.map((thread) => thread.updated_at),
    ]);
    const isCurrent = selectedContainerKey === `application:${application.id}`;
    return {
      kind: "application",
      id: application.id,
      title: application.name,
      summary: application.summary || "",
      promptSummary: application.request_objective || application.summary || application.name,
      statusLabel: statusLabelForApplication(application, goals, threads),
      recencyLabel: "Older",
      latestActivityAt,
      latestResult: latestResultForApplication(application, goals, threads),
      isCurrent,
      isMostRecent: false,
      goals: goals.map((goal) => ({ ...goal, threads: threadsByGoal.get(goal.id) || [] })),
      threads,
      goalCount: application.goal_count || goals.length,
      threadCount: threads.length,
      selectionParams: { application_id: application.id },
    };
  });

  const selectedPlanInCollection = (payload.application_plans || []).find((plan) => plan.id === selectedPlan?.id);
  const planRows = selectedPlan && !selectedPlanInCollection
    ? [...(payload.application_plans || []), selectedPlan]
    : payload.application_plans || [];

  const planContainers: ComposerWorkContainer[] = planRows
    .filter((plan) => !plan.application_id || !appIds.has(plan.application_id) || selectedPlan?.id === plan.id)
    .map((plan) => {
      const detail = selectedPlan?.id === plan.id ? selectedPlan : null;
      const latestActivityAt = latestTimestamp([plan.updated_at]);
      const isCurrent = selectedContainerKey === `application_plan:${plan.id}`;
      return {
        kind: "application_plan",
        id: plan.id,
        title: plan.name,
        summary: plan.summary || "",
        promptSummary: plan.request_objective || plan.summary || plan.name,
        statusLabel: statusLabelForPlan(plan),
        recencyLabel: "Older",
        latestActivityAt,
        latestResult: latestResultForPlan(plan, detail),
        isCurrent,
        isMostRecent: false,
        goals: [],
        threads: [],
        goalCount: detail?.generated_goals?.length ?? detail?.generated_plan?.generated_goals?.length ?? 0,
        threadCount: 0,
        selectionParams: { application_plan_id: plan.id, ...(plan.source_factory_key ? { factory_key: plan.source_factory_key } : {}) },
      };
    });

  const containers = [...applicationContainers, ...planContainers].sort((left, right) => {
    const byUpdated = parseTimestamp(right.latestActivityAt) - parseTimestamp(left.latestActivityAt);
    if (byUpdated !== 0) return byUpdated;
    return left.title.localeCompare(right.title);
  });

  if (containers.length > 0) {
    const mostRecentId = containers[0].id;
    const mostRecentKind = containers[0].kind;
    for (const container of containers) {
      container.isMostRecent = container.id === mostRecentId && container.kind === mostRecentKind;
      container.recencyLabel = recencyLabel(container.isCurrent, container.isMostRecent);
    }
  }

  const linkedGoalIds = new Set(
    containers
      .filter((container) => container.kind === "application")
      .flatMap((container) => container.goals.map((goal) => goal.id))
  );
  const unlinkedGoals = allRecentGoals.filter((goal) => !linkedGoalIds.has(goal.id));
  const unlinkedGoalIds = new Set(unlinkedGoals.map((goal) => goal.id));
  const unlinkedThreads = (payload.related_threads || []).filter((thread) => {
    const goalId = String(thread.goal_id || "").trim();
    if (!goalId) return true;
    return unlinkedGoalIds.has(goalId) || !linkedGoalIds.has(goalId);
  });

  const currentContainer =
    containers.find((container) => container.isCurrent) || containers[0] || null;
  const currentTitle = selectedThread?.title
    || selectedGoal?.title
    || currentContainer?.title
    || "No application effort selected";
  const currentStatusLabel = selectedThread?.status
    || selectedGoal?.goal_progress?.goal_progress_status
    || currentContainer?.statusLabel
    || "Idle";
  const currentLatestResult = selectedThread?.thread_diagnostic?.provenance?.summary
    || selectedThread?.thread_diagnostic?.observations?.[0]
    || selectedGoal?.recommendation?.summary
    || currentContainer?.latestResult
    || "Start by selecting an application effort or generating a new plan.";
  const currentLatestActivityAt = latestTimestamp([
    selectedThread?.updated_at,
    selectedGoal?.updated_at,
    currentContainer?.latestActivityAt,
  ]);

  return {
    containers,
    currentContext: {
      title: currentTitle,
      statusLabel: currentStatusLabel ? String(currentStatusLabel).replace(/[_-]+/g, " ") : "Idle",
      latestResult: currentLatestResult,
      latestActivityAt: currentLatestActivityAt,
      container: currentContainer,
    },
    unlinkedGoals,
    unlinkedThreads,
  };
}
