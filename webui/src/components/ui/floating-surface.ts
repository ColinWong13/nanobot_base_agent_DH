/**
 * The one place a floating surface gets its elevation.
 *
 * Everything that hovers over the page -- popover, dropdown, select, tooltip,
 * command palette -- routes through this file, so the shadow is described here
 * once rather than retyped at each call site. That is also why there is no
 * `dark:` shadow override anywhere below: the shadow colour is inside
 * --elevation-*, so the same class is correct in both themes.
 *
 * Levels follow MD3: a menu sits at level 2, a dialog at level 3.
 */

export const floatingSurfaceElevationClassName =
  "bg-popover text-popover-foreground shadow-elevation-2";

export const floatingSurfaceVisualClassName =
  `rounded-floating p-1.5 ${floatingSurfaceElevationClassName}`;

/** MD3 scrims the page at 32% rather than tinting it, so the dialog keeps its
    own tonal contrast instead of being dimmed along with everything else. */
export const modalOverlayClassName =
  "fixed inset-0 z-50 bg-black/32 backdrop-blur-[8px] data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0";

export const modalSurfaceClassName =
  "bg-surface-container-high text-foreground shadow-elevation-3";

export const floatingSurfaceClassName =
  `${floatingSurfaceVisualClassName} z-50 overflow-x-hidden overflow-y-auto overscroll-contain scrollbar-thin scrollbar-track-transparent`;

export const floatingSurfaceMotionClassName =
  "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0";

export const floatingItemClassName =
  "relative flex min-h-8 select-none items-center gap-2 rounded-control px-2.5 py-2 text-[13px] outline-none transition-colors [&>svg]:h-4 [&>svg]:w-4 [&>svg]:shrink-0";

/**
 * MD3 state layer: focus is the on-surface colour at 12%, not a second colour.
 * Expressed against --foreground so one class covers both themes -- the old
 * `dark:bg-white/[0.08]` was the same idea written twice by hand.
 */
export const floatingItemFocusClassName =
  "focus:bg-foreground/[0.12] focus:text-foreground";
