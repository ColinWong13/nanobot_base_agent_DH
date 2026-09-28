import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * MD3 buttons are pills at every size, and every state change is a *state
 * layer* -- the on-colour at low opacity over the same fill -- rather than a
 * second colour. `bg-primary/90` is that idea with the opacity applied to the
 * fill instead of a separate overlay, which composites to the same thing here
 * and needs no extra element.
 *
 * `ghost` deliberately does not force `text-primary`. MD3's text button is
 * primary-coloured, but its *standard icon button* is on-surface-variant, and
 * in this app a ghost button is almost always an icon action sitting next to
 * content it should not compete with.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-full text-sm font-medium ring-offset-background transition-[color,background-color,border-color,box-shadow,transform] duration-200 ease-standard active:scale-95 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 motion-reduce:active:scale-100",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        // MD3 outlined: outlined in `outline`, still labelled in primary, and
        // with no container of its own -- so it sits on a card as happily as on
        // the page.
        outline:
          "border border-outline bg-transparent text-primary hover:bg-primary/[0.08]",
        // MD3 filled tonal: the secondary-container role, which is exactly what
        // `secondary` already aliases.
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        // MD3 elevated: no container contrast, so it lifts with a shadow.
        elevated:
          "bg-surface-container-low text-primary shadow-elevation-1 hover:shadow-elevation-2",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 px-3",
        lg: "h-11 px-8",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
