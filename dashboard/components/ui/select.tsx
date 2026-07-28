/**
 * Select primitive wrapping the native `<select>` element.
 *
 * Native select keeps keyboard and screen-reader behavior for free
 * and avoids a Radix dependency.
 *
 * @module components/ui/select
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/** Props accepted by the Select component. */
export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {}

/**
 * Styled native select. Children should be `<option>` elements.
 *
 * @example
 * ```tsx
 * <Select value={mode} onChange={(e) => setMode(e.target.value)}>
 *   <option value="DEVELOPMENT">Development</option>
 *   <option value="RUNTIME">Runtime</option>
 * </Select>
 * ```
 */
const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "flex h-10 min-h-touch w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background md:min-h-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";

export { Select };
