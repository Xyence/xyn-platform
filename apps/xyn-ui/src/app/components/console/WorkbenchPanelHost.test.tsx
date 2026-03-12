import { act, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkbenchPanelHost from "./WorkbenchPanelHost";
import { emitEntityChange } from "../../utils/entityChangeEvents";

const apiMocks = vi.hoisted(() => ({
  executeAppPalettePrompt: vi.fn(),
  listRuntimeRunsCanvasApi: vi.fn(),
  getRuntimeRunCanvasApi: vi.fn(),
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
    listRuntimeRunsCanvasApi: apiMocks.listRuntimeRunsCanvasApi,
    getRuntimeRunCanvasApi: apiMocks.getRuntimeRunCanvasApi,
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
    expect(screen.getByText("contract ambiguity")).toBeInTheDocument();
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
