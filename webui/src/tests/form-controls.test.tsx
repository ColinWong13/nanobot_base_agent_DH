import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/**
 * MD3 splits what used to be one control into two, and this file is the line
 * between them: a text field is a filled box that focuses on its underline, a
 * search bar is a pill that focuses with a ring.
 *
 * The assertion worth keeping is the one about *not moving*. The underline is
 * an inset shadow rather than a border precisely because a border that
 * thickens on focus reflows the text, so the caret would jump a pixel on every
 * click. That is invisible in a screenshot and obvious in use.
 */
describe("form control focus styles", () => {
  it.each([
    ["input", <Input aria-label="input" />],
    ["textarea", <Textarea aria-label="textarea" />],
  ])("marks focus on the %s underline without moving its text", (label, control) => {
    render(control);
    const element = screen.getByLabelText(label);

    expect(element.className).toContain(
      "shadow-[inset_0_-1px_0_hsl(var(--outline))]",
    );
    expect(element.className).toContain(
      "focus-visible:shadow-[inset_0_-2px_0_hsl(var(--ring))]",
    );
    // Anything that changes the box on focus would move the text with it.
    expect(element.className).not.toMatch(/focus-visible:(ring|border)/);
  });

  it("keeps a search bar a pill, which MD3 treats as its own component", () => {
    render(<Input type="search" aria-label="search" />);
    const element = screen.getByLabelText("search");

    expect(element).toHaveClass("rounded-full");
    expect(element).toHaveClass("focus-visible:ring-2", "focus-visible:ring-inset");
    expect(element.className).not.toContain("rounded-t-compact");
  });
});
