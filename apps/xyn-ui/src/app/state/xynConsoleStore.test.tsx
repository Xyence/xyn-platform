import { useEffect } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { XynConsoleProvider, useXynConsole } from "./xynConsoleStore";

const apiMocks = vi.hoisted(() => ({
  resolveXynIntent: vi.fn(),
  previewXynIntent: vi.fn(),
  applyXynIntent: vi.fn(),
  getXynIntentOptions: vi.fn(),
}));

vi.mock("../../api/xyn", () => ({
  resolveXynIntent: apiMocks.resolveXynIntent,
  previewXynIntent: apiMocks.previewXynIntent,
  applyXynIntent: apiMocks.applyXynIntent,
  getXynIntentOptions: apiMocks.getXynIntentOptions,
}));

function PreviewHarness({ prompt }: { prompt: string }) {
  const { setInputText, session, previewLoading } = useXynConsole();

  useEffect(() => {
    setInputText(prompt);
  }, [prompt, setInputText]);

  return (
    <div>
      <div data-testid="preview-loading">{previewLoading ? "loading" : "idle"}</div>
      <div data-testid="preview-status">{session.previewResolution?.status || ""}</div>
      <div data-testid="preview-summary">{session.previewResolution?.summary || ""}</div>
      <div data-testid="preview-target">{session.previewResolution?.prompt_interpretation?.target_record?.reference || ""}</div>
      <div data-testid="thread-id">{session.threadId || ""}</div>
    </div>
  );
}

describe("xynConsoleStore preview resolution", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("suppresses stale preview responses when typing changes quickly", async () => {
    let view: ReturnType<typeof render> | null = null;
    let resolveFirst: ((value: unknown) => void) | null = null;
    let resolveSecond: ((value: unknown) => void) | null = null;
    apiMocks.previewXynIntent.mockImplementation(({ message }) => {
      if (String(message).includes("router-a")) {
        return new Promise((resolve) => {
          resolveFirst = resolve;
        });
      }
      return new Promise((resolve) => {
        resolveSecond = resolve;
      });
    });

    view = render(
      <XynConsoleProvider>
        <PreviewHarness prompt="create device router-a" />
      </XynConsoleProvider>
    );

    await waitFor(() => expect(apiMocks.previewXynIntent).toHaveBeenCalledTimes(1));

    view.rerender(
      <XynConsoleProvider>
        <PreviewHarness prompt="create device router-b" />
      </XynConsoleProvider>
    );

    await waitFor(() => expect(apiMocks.previewXynIntent).toHaveBeenCalledTimes(2));

    await act(async () => {
      resolveFirst?.({
        status: "IntentResolved",
        artifact_type: null,
        artifact_id: null,
        summary: "stale preview",
        prompt_interpretation: {
          intent_family: "app_operation",
          intent_type: "create_record",
          action: { verb: "create", label: "Create record" },
          fields: [],
          execution_mode: "immediate_execution",
          confidence: 0.9,
          needs_clarification: false,
          capability_state: { state: "enabled" },
          clarification_options: [],
          resolution_notes: [],
          missing_fields: [],
          recognized_spans: [],
          target_record: { reference: "router-a" },
        },
      });
      await Promise.resolve();
    });

    expect(screen.getByTestId("preview-target").textContent).toBe("");

    await act(async () => {
      resolveSecond?.({
        status: "IntentResolved",
        artifact_type: null,
        artifact_id: null,
        summary: "fresh preview",
        prompt_interpretation: {
          intent_family: "app_operation",
          intent_type: "create_record",
          action: { verb: "create", label: "Create record" },
          fields: [],
          execution_mode: "immediate_execution",
          confidence: 0.9,
          needs_clarification: false,
          capability_state: { state: "enabled" },
          clarification_options: [],
          resolution_notes: [],
          missing_fields: [],
          recognized_spans: [],
          target_record: { reference: "router-b" },
        },
      });
      await Promise.resolve();
    });

    await waitFor(() => expect(screen.getByTestId("preview-target").textContent).toBe("router-b"));
    expect(screen.getByTestId("preview-summary").textContent).toBe("fresh preview");
    view.unmount();
  });

  it("stores a safe unavailable preview result when preview resolution fails", async () => {
    let view: ReturnType<typeof render> | null = null;
    apiMocks.previewXynIntent.mockRejectedValue(new Error("network down"));

    view = render(
      <XynConsoleProvider>
        <PreviewHarness prompt="build a new app" />
      </XynConsoleProvider>
    );

    await waitFor(() => expect(screen.getByTestId("preview-status").textContent).toBe("ValidationError"));

    expect(screen.getByTestId("preview-summary").textContent).toBe("Interpretation preview unavailable.");
    expect(screen.getByTestId("preview-loading").textContent).toBe("idle");
    view.unmount();
  });

  it("persists a durable thread id and sends it with preview requests", async () => {
    let view: ReturnType<typeof render> | null = null;
    apiMocks.previewXynIntent.mockResolvedValue({
      status: "IntentResolved",
      artifact_type: null,
      artifact_id: null,
      summary: "preview ok",
      prompt_interpretation: {
        intent_family: "development_work",
        intent_type: "create_and_dispatch_run",
        action: { verb: "dispatch", label: "Dispatch run" },
        fields: [],
        execution_mode: "queued_run",
        confidence: 0.9,
        needs_clarification: false,
        capability_state: { state: "unknown" },
        clarification_options: [],
        resolution_notes: [],
        missing_fields: [],
        recognized_spans: [],
      },
    });

    view = render(
      <XynConsoleProvider>
        <PreviewHarness prompt="continue Epic G implementation" />
      </XynConsoleProvider>
    );

    await waitFor(() => expect(apiMocks.previewXynIntent).toHaveBeenCalledTimes(1));

    const firstThreadId = screen.getByTestId("thread-id").textContent || "";
    expect(firstThreadId).not.toBe("");
    const firstCall = apiMocks.previewXynIntent.mock.calls[0]?.[0];
    expect(firstCall?.context?.thread_id).toBe(firstThreadId);

    view.rerender(
      <XynConsoleProvider>
        <PreviewHarness prompt="continue Epic G implementation with tests" />
      </XynConsoleProvider>
    );

    await waitFor(() => expect(apiMocks.previewXynIntent).toHaveBeenCalledTimes(2));

    expect(screen.getByTestId("thread-id").textContent).toBe(firstThreadId);
    const secondCall = apiMocks.previewXynIntent.mock.calls[1]?.[0];
    expect(secondCall?.context?.thread_id).toBe(firstThreadId);
    view.unmount();
  });
});
