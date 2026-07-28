"use client";

/**
 * Token budget consumption indicator.
 *
 * Shows a progress bar of consumed/budget tokens, colored by severity, and
 * surfaces a warning badge once consumption passes the configured threshold
 * (80% by default) as determined by `isBudgetWarning`.
 *
 * @module components/costs/budget-indicator
 */

import * as React from "react";
import { AlertTriangle } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { isBudgetWarning } from "@/lib/utils/cost-aggregation";

/** Default warning threshold ratio (80% of budget). */
export const DEFAULT_BUDGET_THRESHOLD = 0.8;

/** Props accepted by the BudgetIndicator component. */
export interface BudgetIndicatorProps {
  /** Tokens consumed so far. */
  consumed: number;
  /** Total token budget. A non-positive budget renders as unlimited. */
  budget: number;
  /** Warning threshold ratio. Defaults to 0.8. */
  threshold?: number;
  /** Optional label rendered above the bar (e.g., task title). */
  label?: string;
  /** Additional classes for the wrapper. */
  className?: string;
}

/**
 * Bar fill color by consumption severity.
 *
 * Shades are picked so the fill clears 3:1 against the muted track in both
 * themes (SC 1.4.11). Severity is also stated in the adjacent token count
 * and warning badge, so it never depends on the fill color alone.
 */
function fillClass(ratio: number): string {
  if (ratio > DEFAULT_BUDGET_THRESHOLD) return "bg-red-700 dark:bg-red-500";
  if (ratio >= 0.5) return "bg-yellow-700 dark:bg-yellow-500";
  return "bg-green-700 dark:bg-green-500";
}

/**
 * Progress indicator for a work unit's token budget.
 *
 * Colors: green below 50%, yellow from 50% to 80%, red above 80%.
 *
 * @example
 * ```tsx
 * <BudgetIndicator
 *   label="Migrate patient intake form"
 *   consumed={task.tokens_consumed}
 *   budget={task.token_budget}
 * />
 * ```
 */
export function BudgetIndicator({
  consumed,
  budget,
  threshold = DEFAULT_BUDGET_THRESHOLD,
  label,
  className,
}: BudgetIndicatorProps) {
  const hasBudget = budget > 0;
  const ratio = hasBudget ? Math.max(0, consumed) / budget : 0;
  const percent = Math.min(100, Math.round(ratio * 100));
  const warning = isBudgetWarning(consumed, budget, threshold);

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {label ? <span className="truncate font-medium">{label}</span> : null}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {consumed.toLocaleString()} /{" "}
          {hasBudget ? budget.toLocaleString() : "∞"} tokens
        </span>
        {warning ? (
          <Badge variant="destructive" className="gap-1">
            <AlertTriangle className="h-3 w-3" aria-hidden="true" />
            {percent}% of budget
          </Badge>
        ) : null}
      </div>

      <div
        role="progressbar"
        aria-valuenow={hasBudget ? percent : 0}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={
          hasBudget
            ? `${percent}% of budget — ${consumed.toLocaleString()} of ${budget.toLocaleString()} tokens${
                warning ? ", over the warning threshold" : ""
              }`
            : `${consumed.toLocaleString()} tokens, no budget limit`
        }
        aria-label={
          label ? `Token budget consumed for ${label}` : "Token budget consumed"
        }
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn(
            "h-full rounded-full transition-all",
            hasBudget ? fillClass(ratio) : "bg-muted-foreground/30",
          )}
          style={{ width: `${hasBudget ? percent : 0}%` }}
        />
      </div>
    </div>
  );
}
