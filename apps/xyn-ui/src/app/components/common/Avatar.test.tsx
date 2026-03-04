import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Avatar, { colorFromIdentity, computeInitials } from "./Avatar";

describe("Avatar", () => {
  it("computes initials from display name", () => {
    expect(computeInitials("John Restivo", "")).toBe("JR");
  });

  it("computes initials from email local part when name is missing", () => {
    expect(computeInitials("", "jrestivo@xyence.io")).toBe("JR");
  });

  it("creates deterministic color from identity", () => {
    expect(colorFromIdentity("abc-123")).toBe(colorFromIdentity("abc-123"));
  });

  it("renders fallback initials when no src", () => {
    render(<Avatar name="Jane Doe" email="" identityKey="sub-1" />);
    expect(screen.getByText("JD")).toBeInTheDocument();
  });

  it("falls back to initials when image load fails", () => {
    render(<Avatar src="https://example.com/a.png" name="Jane Doe" email="" identityKey="sub-1" />);
    const image = screen.getByRole("img");
    fireEvent.error(image);
    expect(screen.getByText("JD")).toBeInTheDocument();
  });
});
