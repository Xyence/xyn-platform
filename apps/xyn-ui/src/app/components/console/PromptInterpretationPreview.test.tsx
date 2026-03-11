import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PromptInterpretationPreview from "./PromptInterpretationPreview";

const baseInterpretation = {
  intent_family: "app_operation",
  intent_type: "create_record",
  action: { verb: "create", label: "Create record" },
  fields: [],
  confidence: 0.9,
  needs_clarification: false,
  capability_state: { state: "enabled" },
  clarification_options: [],
  resolution_notes: [],
  missing_fields: [],
  recognized_spans: [],
};

describe("PromptInterpretationPreview", () => {
  it("renders every current execution mode explicitly", () => {
    const modes = [
      ["immediate_execution", "Immediate execution"],
      ["queued_run", "Queued run"],
      ["work_item_creation", "Create work item"],
      ["work_item_continuation", "Continue work item"],
      ["awaiting_clarification", "Awaiting clarification"],
      ["awaiting_review", "Awaiting review"],
      ["blocked", "Blocked"],
    ] as const;

    for (const [execution_mode, label] of modes) {
      const { unmount } = render(
        <PromptInterpretationPreview
          inputText="create device"
          interpretation={{ ...baseInterpretation, execution_mode }}
        />
      );
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("renders every current capability state explicitly", () => {
    const states = [
      ["enabled", "Enabled capability"],
      ["known_but_disabled", "Known but disabled"],
      ["unknown", "Unknown"],
      ["unavailable", "Unavailable"],
    ] as const;

    for (const [state, label] of states) {
      const { unmount } = render(
        <PromptInterpretationPreview
          inputText="create device"
          interpretation={{ ...baseInterpretation, execution_mode: "immediate_execution", capability_state: { state } }}
        />
      );
      expect(screen.getByText(label)).toBeInTheDocument();
      unmount();
    }
  });

  it("shows explicit unavailable messaging when no interpretation is present", () => {
    render(
      <PromptInterpretationPreview
        inputText="build a new app"
        interpretation={null}
        resolutionStatus="DraftReady"
        resolutionSummary="Will create and submit an app intent draft."
      />
    );

    expect(screen.getByText("Will create and submit an app intent draft.")).toBeInTheDocument();
  });
});
