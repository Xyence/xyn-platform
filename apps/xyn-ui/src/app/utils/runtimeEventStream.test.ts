import { describe, expect, it } from "vitest";

import { applyRuntimeEventToRunDetail, applyRuntimeEventToRuns, runtimeEventToActivityEntry, upsertActivityEntry } from "./runtimeEventStream";
import type { RuntimeRunDetail, RuntimeRunSummary, RuntimeStreamEvent } from "../../api/types";

describe("runtimeEventStream helpers", () => {
  it("applies runtime events to run summaries idempotently", () => {
    const base: RuntimeRunSummary[] = [
      {
        id: "run-1",
        run_id: "run-1",
        work_item_id: "wi-1",
        worker_type: "codex_local",
        worker_id: null,
        status: "queued",
        summary: "Queued",
        created_at: "2026-03-11T10:00:00Z",
        queued_at: null,
        started_at: null,
        completed_at: null,
        heartbeat_at: null,
        elapsed_time_seconds: 0,
        heartbeat_freshness: "missing",
        target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      },
    ];
    const event: RuntimeStreamEvent = {
      event_id: "evt-1",
      event_type: "run.started",
      created_at: "2026-03-11T10:00:05Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "running",
      title: "Run started · run-1",
      message: "Run started · run-1",
      payload: { worker_id: "worker-1", started_at: "2026-03-11T10:00:05Z", status: "running" },
    };

    const once = applyRuntimeEventToRuns(base, event);
    const twice = applyRuntimeEventToRuns(once, event);
    expect(once).toHaveLength(1);
    expect(twice).toHaveLength(1);
    expect(twice[0].status).toBe("running");
    expect(twice[0].worker_id).toBe("worker-1");
  });

  it("applies step and artifact events to run detail without duplication", () => {
    const detail: RuntimeRunDetail = {
      id: "run-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      worker_id: "worker-1",
      status: "running",
      summary: "Running",
      created_at: "2026-03-11T10:00:00Z",
      queued_at: null,
      started_at: "2026-03-11T10:00:05Z",
      completed_at: null,
      heartbeat_at: "2026-03-11T10:00:10Z",
      elapsed_time_seconds: 5,
      heartbeat_freshness: "fresh",
      target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      failure_reason: null,
      escalation_reason: null,
      prompt: { title: "Run", body: "Run" },
      policy: { auto_continue: true, max_retries: 1, require_human_review_on_failure: false, timeout_seconds: 1800 },
      steps: [],
      artifacts: [],
    };
    const stepEvent: RuntimeStreamEvent = {
      event_id: "evt-step",
      event_type: "run.step.completed",
      created_at: "2026-03-11T10:00:06Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "running",
      title: "Run step completed: inspect repository",
      message: "Run step completed: inspect repository",
      payload: { step_id: "step-1", step_key: "inspect_repository", label: "Inspect repository", sequence_no: 1, status: "completed" },
    };
    const artifactEvent: RuntimeStreamEvent = {
      event_id: "evt-artifact",
      event_type: "run.artifact.created",
      created_at: "2026-03-11T10:00:07Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "running",
      title: "Run artifact created",
      message: "Run artifact created: summary",
      payload: { artifact_id: "artifact-1", artifact_type: "summary", label: "Final summary", uri: "artifact://runs/run-1/final_summary.md" },
    };

    const once = applyRuntimeEventToRunDetail(detail, stepEvent);
    const twice = applyRuntimeEventToRunDetail(once, stepEvent);
    const withArtifact = applyRuntimeEventToRunDetail(twice, artifactEvent);
    const withDuplicateArtifact = applyRuntimeEventToRunDetail(withArtifact, artifactEvent);

    expect(withDuplicateArtifact.steps).toHaveLength(1);
    expect(withDuplicateArtifact.artifacts).toHaveLength(1);
    expect(withDuplicateArtifact.artifacts[0].uri).toContain("final_summary.md");
  });

  it("keeps runtime activity entries de-duplicated and ordered", () => {
    const first = runtimeEventToActivityEntry({
      event_id: "evt-1",
      event_type: "run.started",
      created_at: "2026-03-11T10:00:00Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "running",
      title: "Run started · run-1",
      message: "Run started · run-1",
      payload: {},
    });
    const second = runtimeEventToActivityEntry({
      event_id: "evt-2",
      event_type: "run.completed",
      created_at: "2026-03-11T10:01:00Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "succeeded",
      title: "Run completed · run-1",
      message: "Run completed · run-1",
      payload: {},
    });

    const merged = upsertActivityEntry(upsertActivityEntry([], first), second);
    const deduped = upsertActivityEntry(merged, second);
    expect(deduped).toHaveLength(2);
    expect(deduped[0].summary).toBe("Run completed · run-1");
  });

  it("maps failed and completed runtime events to escalation and execution summary messages", () => {
    const failed = runtimeEventToActivityEntry({
      event_id: "evt-fail",
      event_type: "run.failed",
      created_at: "2026-03-11T10:00:00Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "failed",
      title: "Run failed",
      message: "Run failed: tests_failed",
      payload: { failure_reason: "tests_failed" },
    });
    const completed = runtimeEventToActivityEntry({
      event_id: "evt-complete",
      event_type: "run.completed",
      created_at: "2026-03-11T10:01:00Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "succeeded",
      title: "Run completed · run-1",
      message: "Run completed · run-1",
      payload: {},
    });

    expect(failed.conversation_message?.message_type).toBe("escalation");
    expect(failed.conversation_message?.reason).toBe("tests_failed");
    expect(failed.conversation_message?.options).toContain("retry run");
    expect(completed.conversation_message?.message_type).toBe("execution_summary");
  });

  it("does not let stale non-terminal events overwrite terminal run state", () => {
    const runs: RuntimeRunSummary[] = [
      {
        id: "run-1",
        run_id: "run-1",
        work_item_id: "wi-1",
        worker_type: "codex_local",
        worker_id: "worker-1",
        status: "succeeded",
        summary: "Run completed",
        created_at: "2026-03-11T10:00:00Z",
        queued_at: null,
        started_at: "2026-03-11T10:00:05Z",
        completed_at: "2026-03-11T10:02:00Z",
        heartbeat_at: "2026-03-11T10:01:59Z",
        elapsed_time_seconds: 115,
        heartbeat_freshness: "fresh",
        target: { repo: "xyn", branch: "develop", workspace_id: "ws-1", artifact_id: null },
      },
    ];
    const staleEvent: RuntimeStreamEvent = {
      event_id: "evt-late",
      event_type: "run.step.completed",
      created_at: "2026-03-11T10:01:30Z",
      workspace_id: "ws-1",
      run_id: "run-1",
      work_item_id: "wi-1",
      worker_type: "codex_local",
      status: "running",
      title: "Run step completed",
      message: "Run step completed",
      payload: { step_id: "step-1", step_key: "execute_codex", label: "Execute codex", sequence_no: 3, status: "completed" },
    };

    const nextRuns = applyRuntimeEventToRuns(runs, staleEvent);
    expect(nextRuns[0].status).toBe("succeeded");

    const detail: RuntimeRunDetail = {
      ...runs[0],
      failure_reason: null,
      escalation_reason: null,
      prompt: { title: "Run", body: "Run" },
      policy: { auto_continue: true, max_retries: 1, require_human_review_on_failure: false, timeout_seconds: 1800 },
      steps: [],
      artifacts: [],
    };
    const nextDetail = applyRuntimeEventToRunDetail(detail, staleEvent);
    expect(nextDetail.status).toBe("succeeded");
    expect(nextDetail.steps).toHaveLength(0);
  });
});
