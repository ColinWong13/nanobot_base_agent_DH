import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * MD3 chips. Short, pill-shaped labels for a small piece of metadata — the
 * registry's tier badges (CCF-A, FT50) are the first caller.
 *
 * Kept to display duty on purpose: when a chip is interactive it is a button
 * and should be built from `Button` with `rounded-pill`, so it inherits the
 * focus ring, disabled handling and keyboard behaviour instead of re-deriving
 * them here. `selected` only restyles; the caller owns `aria-pressed`.
 */
const chipVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-pill font-medium",
  {
    variants: {
      variant: {
        // Filled: MD3's "assist" chip. The default because a tier badge is
        // usually the thing the eye should land on first.
        filled: "bg-secondary text-secondary-foreground",
        // Low-emphasis: for tiers that are present but not the point.
        tonal: "bg-muted text-muted-foreground",
        outline: "border border-border text-muted-foreground",
        // Reserve for a genuinely top-tier mark; tertiary is the role MD3 keeps
        // for accents that must not read as a primary action.
        tertiary: "bg-tertiary/15 text-tertiary",
      },
      size: {
        default: "h-6 px-2.5 text-xs",
        sm: "h-5 px-2 text-[11px]",
        lg: "h-8 px-3.5 text-sm",
      },
      selected: {
        true: "bg-secondary text-secondary-foreground",
        false: "",
      },
    },
    defaultVariants: {
      variant: "filled",
      size: "default",
      selected: false,
    },
  },
);

interface ChipProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof chipVariants> {}

const Chip = React.forwardRef<HTMLSpanElement, ChipProps>(
  ({ className, variant, size, selected, ...props }, ref) => (
    <span
      ref={ref}
      className={cn(chipVariants({ variant, size, selected, className }))}
      {...props}
    />
  ),
);
Chip.displayName = "Chip";

export { Chip, chipVariants };
