import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RulesBrowserPanel from "./RulesBrowserPanel";

const apiMocks = vi.hoisted(() => ({
  getRulesBrowser: vi.fn(),
}));

vi.mock("../../../api/xyn", async () => {
  const actual = await vi.importActual<typeof import("../../../api/xyn")>("../../../api/xyn");
  return {
    ...actual,
    getRulesBrowser: apiMocks.getRulesBrowser,
  };
});

describe("RulesBrowserPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("groups rules by family and shows enforcement/access badges", async () => {
    apiMocks.getRulesBrowser.mockResolvedValue({
      bundles: [
        {
          bundle_id: "policy.team-lunch-poll",
          title: "Team Lunch Poll Policy Bundle",
          app_slug: "app.team-lunch-poll",
          artifact_slug: "policy.team-lunch-poll",
          rule_count: 2,
          compiled_rule_count: 1,
          documented_rule_count: 1,
        },
      ],
      groups: [
        { family: "validation_policies", label: "Validation Policies", count: 1, enforced: 1, documented_only: 0 },
        { family: "trigger_policies", label: "Trigger Policies", count: 1, enforced: 0, documented_only: 1 },
      ],
      rules: [
        {
          id: "policy-1",
          title: "Vote gate",
          description: "Votes allowed when poll is open.",
          family: "validation_policies",
          family_label: "Validation Policies",
          enforced: true,
          enforcement_status: "enforced",
          enforcement_stage: "runtime_enforced",
          scope: "generated_runtime",
          ownership: "generated_application",
          editable: true,
          source_policy_bundle: {
            bundle_id: "policy.team-lunch-poll",
            artifact_slug: "policy.team-lunch-poll",
            app_slug: "app.team-lunch-poll",
          },
        },
        {
          id: "policy-2",
          title: "Set poll selected",
          description: "When option selected, set poll status selected.",
          family: "trigger_policies",
          family_label: "Trigger Policies",
          enforced: false,
          enforcement_status: "documented_only",
          enforcement_stage: "not_compiled",
          scope: "generated_runtime",
          ownership: "generated_application",
          editable: true,
          source_policy_bundle: {
            bundle_id: "policy.team-lunch-poll",
            artifact_slug: "policy.team-lunch-poll",
            app_slug: "app.team-lunch-poll",
          },
        },
      ],
      access: { filtered_out_bundles: 0 },
    });

    render(<RulesBrowserPanel workspaceId="ws-1" artifactSlug="app.team-lunch-poll" />);

    expect(await screen.findByText("Validation Policies")).toBeInTheDocument();
    expect(screen.getByText("Trigger Policies")).toBeInTheDocument();
    expect(screen.getByText("Enforced")).toBeInTheDocument();
    expect(screen.getByText("Documented-only")).toBeInTheDocument();
    expect(screen.getAllByText("Editable").length).toBeGreaterThan(0);
  });

  it("renders bundle chooser when multiple bundles are returned", async () => {
    apiMocks.getRulesBrowser.mockResolvedValue({
      bundles: [
        {
          bundle_id: "policy.team-lunch-poll",
          title: "Team Lunch Poll Policy Bundle",
          app_slug: "app.team-lunch-poll",
          artifact_slug: "policy.team-lunch-poll",
          rule_count: 2,
          compiled_rule_count: 1,
          documented_rule_count: 1,
        },
        {
          bundle_id: "policy.deal-finder",
          title: "Deal Finder Policy Bundle",
          app_slug: "app.deal-finder",
          artifact_slug: "policy.deal-finder",
          rule_count: 1,
          compiled_rule_count: 0,
          documented_rule_count: 1,
        },
      ],
      groups: [],
      rules: [],
      access: { filtered_out_bundles: 0 },
    });

    render(<RulesBrowserPanel workspaceId="ws-1" />);
    expect(await screen.findByText("Policy Bundles")).toBeInTheDocument();
    expect(screen.getByText(/Team Lunch Poll Policy Bundle/)).toBeInTheDocument();
    expect(screen.getByText(/Deal Finder Policy Bundle/)).toBeInTheDocument();
  });
});
