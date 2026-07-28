/**
 * Button primitive with variant and size support.
 *
 * Minimal shadcn/ui-compatible implementation built on
 * class-variance-authority. No Radix dependency required.
 *
 * @module components/ui/button
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** Class variants for the Button component. */
export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/90",
        outline:
          "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-secondary/80",
      },
      /**
       * Sizes keep a 44x44px minimum hit area below the `md` breakpoint
       * for touch input, then relax to their compact desktop height.
       */
      size: {
        default: "h-10 min-h-touch px-4 py-2 md:min-h-0",
        sm: "h-9 min-h-touch rounded-md px-3 md:min-h-0",
        lg: "h-11 rounded-md px-8",
        icon: "h-10 min-h-touch w-10 min-w-touch md:min-h-0 md:min-w-0",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

/** Props accepted by the Button component. */
export interface ButtonProps
  extends
    React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

/**
 * Accessible button with styling variants.
 *
 * @example
 * ```tsx
 * <Button variant="outline" size="sm">Refresh</Button>
 * ```
 */
const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, type = "button", ...props }, ref) => (
    <button
      ref={ref}
      type={type}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export { Button };
