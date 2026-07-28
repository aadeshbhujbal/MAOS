/**
 * Input primitive for single-line text entry.
 *
 * @module components/ui/input
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/** Props accepted by the Input component. */
export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {}

/**
 * Styled text input with focus ring and disabled states.
 */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type = "text", ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        "flex h-10 min-h-touch w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground md:min-h-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = "Input";

export { Input };
