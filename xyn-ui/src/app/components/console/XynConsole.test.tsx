import { useEffect } from "react";
import { MemoryRouter } from "react-router-dom";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import XynConsoleNode from "./XynConsoleNode";
import { XynConsoleProvider, useXynConsole } from "../../state/xynConsoleStore";

const apiMocks = vi.hoisted(() => ({
  resolveXynIntent: vi.fn(),
  applyXynIntent: vi.fn(),
  getXynIntentOptions: vi.fn(),
  getRecentArtifacts: vi.fn(),
}));

vi.mock("../../../api/xyn", () => ({
  resolveXynIntent: apiMocks.resolveXynIntent,
  applyXynIntent: apiMocks.applyXynIntent,
  getXynIntentOptions: apiMocks.getXynIntentOptions,
  getRecentArtifacts: apiMocks.getRecentArtifacts,
}));

function renderConsole() {
  return render(
    <MemoryRouter>
      <XynConsoleProvider>
        <XynConsoleNode />
      </XynConsoleProvider>
    </MemoryRouter>
  );
}

function ConsoleBridgeHarness({
  artifactId,
  artifactType = "ArticleDraft",
  onApplyPatch,
  onFocusField,
  onApplyFieldValue,
}: {
  artifactId: string;
  artifactType?: "ArticleDraft" | "ContextPack";
  onApplyPatch: (patch: Record<string, unknown>) => { appliedFields: string[]; ignoredFields: string[] };
  onFocusField?: (field: string) => boolean;
  onApplyFieldValue?: (field: string, value: unknown) => boolean;
}) {
  const { setContext, registerEditorBridge, unregisterEditorBridge } = useXynConsole();

  useEffect(() => {
    const context = { artifact_id: artifactId, artifact_type: artifactType };
    setContext(context);
    registerEditorBridge(context, {
      getFormSnapshot: () => ({ title: "Existing title", category: "demo", format: "standard", summary: "Current summary", tags: [], body: "Body" }),
      applyPatchToForm: onApplyPatch,
      focusField: onFocusField || (() => true),
      applyFieldValue: onApplyFieldValue,
    });
    return () => {
      unregisterEditorBridge(context);
    };
  }, [artifactId, artifactType, onApplyFieldValue, onApplyPatch, onFocusField, registerEditorBridge, setContext, unregisterEditorBridge]);

  return null;
}

function ConsoleRouteChangeHarness({ path }: { path: string }) {
  const { handleRouteChange } = useXynConsole();

  useEffect(() => {
    handleRouteChange(path);
  }, [handleRouteChange, path]);

  return null;
}

function renderConsoleWithBridge({
  artifactId = "art-1",
  artifactType = "ArticleDraft",
  onApplyPatch,
  onFocusField,
  onApplyFieldValue,
}: {
  artifactId?: string;
  artifactType?: "ArticleDraft" | "ContextPack";
  onApplyPatch: (patch: Record<string, unknown>) => { appliedFields: string[]; ignoredFields: string[] };
  onFocusField?: (field: string) => boolean;
  onApplyFieldValue?: (field: string, value: unknown) => boolean;
}) {
  return render(
    <MemoryRouter>
      <XynConsoleProvider>
        <ConsoleBridgeHarness
          artifactId={artifactId}
          artifactType={artifactType}
          onApplyPatch={onApplyPatch}
          onFocusField={onFocusField}
          onApplyFieldValue={onApplyFieldValue}
        />
        <XynConsoleNode />
      </XynConsoleProvider>
    </MemoryRouter>
  );
}

describe("XynConsole", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    apiMocks.getRecentArtifacts.mockResolvedValue({
      items: [
        {
          artifact_id: "a-1",
          artifact_type: "article",
          artifact_state: "provisional",
          title: "Recent Draft",
          updated_at: new Date().toISOString(),
          route: "/app/artifacts/a-1",
        },
      ],
    });
  });

  it("opens with Cmd/Ctrl+K and focuses input", async () => {
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await waitFor(() => expect(input).toHaveFocus());
    await screen.findByText("Recent");
  });

  it("submits intent with Enter from the textarea", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "UnsupportedIntent",
      action_type: "ValidateDraft",
      artifact_type: null,
      artifact_id: null,
      summary: "Could not parse intent proposal.",
    });
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create explainer draft");
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(apiMocks.resolveXynIntent).toHaveBeenCalledTimes(1));
  });

  it("keeps Shift+Enter as newline and does not submit", async () => {
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "line one");
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(apiMocks.resolveXynIntent).not.toHaveBeenCalled();
  });

  it("blocks close when a proposal is pending until cancel/apply", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "ProposedPatch",
      action_type: "ProposePatch",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Patch proposal is ready.",
      proposed_patch: {
        changes: [{ field: "summary", from: "old", to: "new" }],
        patch_object: { summary: "new" },
        requires_confirmation: true,
      },
    });

    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "update summary");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    await screen.findByText("Proposed patch");
    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.getByText("You have a pending proposal. Apply or cancel.")).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Xyn Console" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Xyn Console" })).not.toBeInTheDocument());
  });

  it("supports resolve proposed patch then apply to draft-ready", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "ProposedPatch",
      action_type: "ProposePatch",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Patch proposal is ready.",
      proposed_patch: {
        changes: [{ field: "tags", from: [], to: ["governance"] }],
        patch_object: { tags: ["governance"] },
        requires_confirmation: true,
      },
    });
    apiMocks.applyXynIntent.mockResolvedValue({
      status: "DraftReady",
      action_type: "ApplyPatch",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Patch applied successfully.",
    });

    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });

    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "add tags governance");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    await screen.findByText("Proposed patch");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await screen.findByText("Patch applied successfully.");
    expect(apiMocks.applyXynIntent).toHaveBeenCalled();
  });

  it("shows options and injects selected value", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "MissingFields",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: null,
      summary: "Need more fields.",
      missing_fields: [{ field: "category", reason: "required", options_available: true }],
    });
    apiMocks.getXynIntentOptions.mockResolvedValue({
      artifact_type: "ArticleDraft",
      field: "category",
      options: ["web", "guide"],
    });

    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create draft");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));

    await screen.findByText("Missing fields");
    await userEvent.click(screen.getByRole("button", { name: "Show options" }));
    const guideOption = await screen.findByRole("button", { name: "guide" });
    await userEvent.click(guideOption);

    await waitFor(() => expect(screen.getByDisplayValue(/category: guide/i)).toBeInTheDocument());
  });

  it("keeps recent section visible when user types input", async () => {
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await screen.findByText("Recent");
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create draft");
    await waitFor(() => expect(screen.getByText("Recent")).toBeInTheDocument());
  });

  it("hides deprecated articles in recent by default and reveals them when enabled", async () => {
    apiMocks.getRecentArtifacts.mockResolvedValue({
      items: [
        {
          artifact_id: "a-1",
          artifact_type: "article",
          artifact_state: "deprecated",
          title: "Deprecated Article",
          updated_at: new Date().toISOString(),
          route: "/app/artifacts/a-1",
        },
        {
          artifact_id: "cp-1",
          artifact_type: "context_pack",
          artifact_state: "canonical",
          title: "Context Pack A",
          updated_at: new Date().toISOString(),
          route: "/app/context-packs?pack=cp-1",
        },
      ],
    });

    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await screen.findByText("Recent");

    expect(screen.queryByRole("listitem", { name: /Deprecated Article/i })).not.toBeInTheDocument();
    expect(screen.getByRole("listitem", { name: /Context Pack A/i })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: /Show deprecated/i }));
    expect(screen.getByRole("listitem", { name: /Deprecated Article/i })).toBeInTheDocument();
  });

  it("shows clear action for global result and returns to recent", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "UnsupportedIntent",
      action_type: "ValidateDraft",
      artifact_type: null,
      artifact_id: null,
      summary: "Could not parse intent proposal.",
    });
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "???");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Could not parse intent proposal.");
    const clearButtons = screen.getAllByRole("button", { name: "Clear" });
    await userEvent.click(clearButtons[clearButtons.length - 1]);
    await screen.findByText("Recent");
  });

  it("opens recent artifact row and closes panel", async () => {
    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    await screen.findByText("Recent");
    await userEvent.click(screen.getByRole("listitem", { name: /Recent Draft/i }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Xyn Console" })).not.toBeInTheDocument());
  });

  it("applies proposed patch to local form without backend call", async () => {
    const onApplyPatch = vi.fn().mockReturnValue({ appliedFields: ["summary"], ignoredFields: [] });
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "ProposedPatch",
      action_type: "ProposePatch",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Patch proposal is ready.",
      proposed_patch: {
        changes: [{ field: "summary", from: "old", to: "new" }],
        patch_object: { summary: "new" },
        requires_confirmation: true,
      },
    });

    renderConsoleWithBridge({ onApplyPatch });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "improve summary");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Proposed patch");
    await userEvent.click(screen.getByRole("button", { name: "Apply to form" }));

    expect(onApplyPatch).toHaveBeenCalledWith({ summary: "new" });
    expect(apiMocks.applyXynIntent).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.getAllByText("Applied locally (unsaved).").length).toBeGreaterThan(0));
  });

  it("focuses missing field via console action", async () => {
    const onApplyPatch = vi.fn().mockReturnValue({ appliedFields: [], ignoredFields: [] });
    const onFocusField = vi.fn().mockReturnValue(true);
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "MissingFields",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Need more fields.",
      missing_fields: [{ field: "intent", reason: "required", options_available: false }],
    });

    renderConsoleWithBridge({ onApplyPatch, onFocusField });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create explainer");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Missing fields");
    await userEvent.click(screen.getByRole("button", { name: "Focus field" }));
    expect(onFocusField).toHaveBeenCalledWith("intent");
  });

  it("adds missing field hint to prompt in global context", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "MissingFields",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: null,
      summary: "Need more fields.",
      missing_fields: [{ field: "intent", reason: "required", options_available: false }],
    });

    renderConsole();
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create explainer video");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Missing fields");
    await userEvent.click(screen.getByRole("button", { name: "Add to prompt" }));
    await waitFor(() => expect(screen.getByDisplayValue(/intent:\s*$/i)).toBeInTheDocument());
  });

  it("applies option directly to form in editor context", async () => {
    const onApplyPatch = vi.fn().mockReturnValue({ appliedFields: [], ignoredFields: [] });
    const onApplyFieldValue = vi.fn().mockReturnValue(true);
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "MissingFields",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: "art-1",
      summary: "Need more fields.",
      missing_fields: [{ field: "category", reason: "required", options_available: true }],
    });
    apiMocks.getXynIntentOptions.mockResolvedValue({
      artifact_type: "ArticleDraft",
      field: "category",
      options: ["web", "guide"],
    });

    renderConsoleWithBridge({ onApplyPatch, onApplyFieldValue });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create draft");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Missing fields");
    await userEvent.click(screen.getByRole("button", { name: "Show options" }));
    await userEvent.click(await screen.findByRole("button", { name: "guide" }));
    expect(onApplyFieldValue).toHaveBeenCalledWith("category", "guide");
    await screen.findByText("Applied locally (unsaved): category.");
  });

  it("clears global ready create session after navigating away from initiate", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "DraftReady",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: "art-123",
      summary: "Draft created.",
      next_actions: [{ label: "Open in Editor", action: "open_editor" }],
    });

    const view = render(
      <MemoryRouter>
        <XynConsoleProvider>
          <ConsoleRouteChangeHarness path="/app/console" />
          <XynConsoleNode />
        </XynConsoleProvider>
      </MemoryRouter>
    );

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create explainer draft");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Draft created.");

    view.rerender(
      <MemoryRouter>
        <XynConsoleProvider>
          <ConsoleRouteChangeHarness path="/app/artifacts/art-123" />
          <XynConsoleNode />
        </XynConsoleProvider>
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.queryByText("Draft created.")).not.toBeInTheDocument());
    expect(screen.queryByText("Open in Editor")).not.toBeInTheDocument();
  });

  it("retains in-progress session when navigating away from initiate", async () => {
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "MissingFields",
      action_type: "CreateDraft",
      artifact_type: "ArticleDraft",
      artifact_id: null,
      summary: "Draft requires additional fields before it can proceed.",
      missing_fields: [{ field: "category", reason: "required", options_available: true }],
    });

    const view = render(
      <MemoryRouter>
        <XynConsoleProvider>
          <ConsoleRouteChangeHarness path="/app/console" />
          <XynConsoleNode />
        </XynConsoleProvider>
      </MemoryRouter>
    );

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "create explainer draft");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Draft requires additional fields before it can proceed.");

    view.rerender(
      <MemoryRouter>
        <XynConsoleProvider>
          <ConsoleRouteChangeHarness path="/app/artifacts/some-id" />
          <XynConsoleNode />
        </XynConsoleProvider>
      </MemoryRouter>
    );

    await screen.findByText("Draft requires additional fields before it can proceed.");
    expect(screen.getByDisplayValue("create explainer draft")).toBeInTheDocument();
  });

  it("sends ContextPack artifact_type on apply when editing a context pack", async () => {
    const onApplyPatch = vi.fn().mockReturnValue({ appliedFields: ["content"], ignoredFields: [] });
    apiMocks.resolveXynIntent.mockResolvedValue({
      status: "ProposedPatch",
      action_type: "ProposePatch",
      artifact_type: "ContextPack",
      artifact_id: "pack-art-1",
      summary: "Patch proposal is ready.",
      proposed_patch: {
        changes: [{ field: "content", from: "{}", to: "{\"k\":\"v\"}" }],
        patch_object: { content: "{\"k\":\"v\"}", format: "json" },
        requires_confirmation: true,
      },
    });
    apiMocks.applyXynIntent.mockResolvedValue({
      status: "DraftReady",
      action_type: "ApplyPatch",
      artifact_type: "ContextPack",
      artifact_id: "pack-art-1",
      summary: "Context pack patch applied successfully.",
    });

    renderConsoleWithBridge({ artifactId: "pack-art-1", artifactType: "ContextPack", onApplyPatch });
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const input = await screen.findByPlaceholderText("Describe what you want to create or change...");
    await userEvent.type(input, "update context pack content");
    await userEvent.click(screen.getByRole("button", { name: "Submit" }));
    await screen.findByText("Proposed patch");
    await userEvent.click(screen.getByRole("button", { name: "Apply & Save" }));
    await waitFor(() =>
      expect(apiMocks.applyXynIntent).toHaveBeenCalledWith(
        expect.objectContaining({
          action_type: "ApplyPatch",
          artifact_type: "ContextPack",
          artifact_id: "pack-art-1",
        })
      )
    );
  });
});
