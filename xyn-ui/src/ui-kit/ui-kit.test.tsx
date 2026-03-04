import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AppShell, Card, Header, Page } from "./index";

describe("ui-kit", () => {
  it("renders basic shell components", () => {
    render(
      <AppShell>
        <Header title="Demo app" />
        <Page>
          <Card>hello</Card>
        </Page>
      </AppShell>
    );
    expect(screen.getByText("Demo app")).toBeInTheDocument();
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
});
