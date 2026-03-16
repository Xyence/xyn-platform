import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import ActionRowCard from "./ActionRowCard";

describe("ActionRowCard", () => {
  it("renders a simple title-only action as a clickable row", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();

    render(<ActionRowCard title="Open workspace" icon={<span>O</span>} onClick={onClick} />);

    const button = screen.getByRole("button", { name: /Open workspace/i });
    expect(button).toBeInTheDocument();
    expect(screen.getByText("Open workspace")).toHaveClass("action-row-card__title");

    await user.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("renders title and description on separate stacked elements", () => {
    render(
      <ActionRowCard
        title="Retry validation"
        description="Queue another validation pass after reviewing the current failure."
        badge={<span className="chip warn">Next step</span>}
        icon={<span>R</span>}
        onClick={() => undefined}
      />,
    );

    expect(screen.getByText("Retry validation")).toHaveClass("action-row-card__title");
    expect(screen.getByText("Queue another validation pass after reviewing the current failure.")).toHaveClass(
      "action-row-card__description",
    );
    expect(screen.getByText("Next step")).toBeInTheDocument();
  });

  it("renders disabled title, description, and reason without button semantics", () => {
    render(
      <ActionRowCard
        title="Open application workspace"
        description="Open the generated application workspace once routing is confirmed."
        disabled
        disabledReason="Workspace routing for the generated application is not confirmed yet."
        icon={<span>W</span>}
      />,
    );

    expect(screen.queryByRole("button", { name: /Open application workspace/i })).not.toBeInTheDocument();
    const card = screen.getByText("Open application workspace").closest(".action-row-card");
    expect(card).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Workspace routing for the generated application is not confirmed yet.")).toHaveClass(
      "action-row-card__reason",
    );
  });

  it("keeps long descriptions readable without collapsing into the title line", () => {
    render(
      <ActionRowCard
        title="Review failure summary"
        description="Inspect the recorded validation notes, compare the deployed runtime evidence, and confirm whether the smoke test failure reflects an environment issue or an application defect."
        icon={<span>F</span>}
        onClick={() => undefined}
      />,
    );

    expect(screen.getByText(/Inspect the recorded validation notes/)).toHaveClass("action-row-card__description");
    expect(screen.getByText("Review failure summary")).toHaveClass("action-row-card__title");
  });
});
