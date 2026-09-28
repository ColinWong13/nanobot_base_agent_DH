import * as React from "react";

import {
  filledFieldClassName,
  searchBarClassName,
} from "@/components/ui/form-control";
import { cn } from "@/lib/utils";

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    // MD3 has two different components here, and `type` already tells them
    // apart: a search bar is a pill, a text field is a filled box. Branching on
    // the attribute the caller was already passing beats adding a variant prop
    // that every one of the 56 call sites would have to learn about.
    const isSearch = type === "search";
    return (
      <input
        type={type}
        className={cn(
          "flex h-10 w-full px-3 py-2 text-sm file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
          isSearch ? searchBarClassName : filledFieldClassName,
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
