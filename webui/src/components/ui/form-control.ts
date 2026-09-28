/**
 * The focus ring for controls that are *not* text fields: calendar cells,
 * run-at pickers, list rows, prompt navigator entries. MD3 gives text fields
 * their own indicator, so that one lives in `filledFieldClassName` instead and
 * this stays a ring.
 */
export const formControlFocusClassName =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/50";

/**
 * MD3 filled text field: a tonal container with the top corners rounded and the
 * bottom ones square, where the underline is the focus affordance -- 1px in
 * `outline` at rest, 2px in `ring` while focused.
 *
 * The underline is an inset box-shadow rather than a border on purpose. A
 * border that thickens on focus pushes the text down a pixel on every click,
 * which reads as a flinch; a shadow cannot move anything.
 */
export const filledFieldClassName =
  "rounded-t-compact rounded-b-none bg-muted shadow-[inset_0_-1px_0_hsl(var(--outline))] focus-visible:outline-none focus-visible:shadow-[inset_0_-2px_0_hsl(var(--ring))]";

/**
 * MD3 search bar. The spec has this as its own component rather than as a
 * decorated text field -- it is a full pill with a leading icon -- so a search
 * box keeps the shape it always had instead of becoming a filled box.
 */
export const searchBarClassName =
  `rounded-full border border-input bg-background ${formControlFocusClassName}`;
