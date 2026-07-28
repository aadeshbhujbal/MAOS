/**
 * Skeleton placeholder shown while data is loading.
 *
 * @module components/ui/skeleton
 */

import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Animated loading placeholder.
 *
 * The placeholder itself is decorative and hidden from assistive
 * technology; the surrounding region carries `role="status"` and
 * `aria-busy="true"` so a single loading announcement is made instead of
 * one per placeholder bar.
 *
 * @example
 * ```tsx
 * <div role="status" aria-busy="true" aria-label="Loading tasks">
 *   <Skeleton className="h-4 w-32" />
 * </div>
 * ```
 */
function Skeleton({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

export { Skeleton };
