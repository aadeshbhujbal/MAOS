"use client";

/**
 * Single task table row with a color-coded state badge.
 *
 * The title is a link to the task's execution trace at `/tasks/[taskId]`;
 * clicking anywhere in the row follows the same route.
 *
 * @module components/tasks/task-row
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { TableCell, TableRow } from "@/components/ui/table";
import { formatTimestamp } from "@/lib/utils/format";
import type { OperatingMode, Task, WorkUnitState } from "@/types";

/**
 * Tailwind classes for each work unit state.
 *
 * assigned = gray, in_progress = blue, awaiting_approval = yellow,
 * completed = green, failed = red, timed_out = orange,
 * permanently_failed = dark red.
 *
 * Text shades are chosen so each label clears 4.5:1 against its own tinted
 * background in both themes (SC 1.4.3). The state name is always rendered
 * as text, so state is never signalled by color alone (SC 1.4.1).
 */
export const STATE_BADGE_CLASSES: Record<WorkUnitState, string> = {
  assigned:
    "bg-gray-500/15 text-gray-700 dark:text-gray-300 border-gray-500/40",
  in_progress:
    "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/40",
  awaiting_approval:
    "bg-yellow-500/15 text-yellow-800 dark:text-yellow-300 border-yellow-500/40",
  completed:
    "bg-green-500/15 text-green-800 dark:text-green-300 border-green-500/40",
  failed: "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/40",
  timed_out:
    "bg-orange-500/15 text-orange-800 dark:text-orange-300 border-orange-500/40",
  permanently_failed:
    "bg-red-900/25 text-red-900 dark:text-red-400 border-red-900/50",
};

/** States a work unit can no longer transition out of. */
export const TERMINAL_STATES: WorkUnitState[] = [
  "completed",
  "failed",
  "timed_out",
  "permanently_failed",
];

/**
 * Resolve the badge class for a state, falling back to a neutral style
 * for values the backend may introduce later.
 *
 * @param state - Work unit state (or any string from the API).
 * @returns Tailwind class string for the badge.
 */
export function stateBadgeClass(state: WorkUnitState | string): string {
  return (
    STATE_BADGE_CLASSES[state as WorkUnitState] ??
    "bg-muted text-muted-foreground border-border"
  );
}

/** Tailwind classes for operating mode badges. */
export const MODE_BADGE_CLASSES: Record<OperatingMode, string> = {
  DEVELOPMENT:
    "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/40",
  RUNTIME:
    "bg-purple-500/15 text-purple-700 dark:text-purple-300 border-purple-500/40",
};

/** Props for {@link StateBadge}. */
export interface StateBadgeProps {
  /** Work unit state to display. */
  state: WorkUnitState | string;
  /** Extra classes appended to the badge. */
  className?: string;
}

/**
 * Color-coded work unit state badge.
 *
 * @example
 * ```tsx
 * <StateBadge state="in_progress" />
 * ```
 */
export function StateBadge({ state, className }: StateBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={cn("whitespace-nowrap", stateBadgeClass(state), className)}
    >
      {String(state).replace(/_/g, " ")}
    </Badge>
  );
}

/** Props for {@link ModeBadge}. */
export interface ModeBadgeProps {
  /** Operating mode to display. */
  mode: OperatingMode;
  /** Extra classes appended to the badge. */
  className?: string;
}

/** Operating mode badge: DEVELOPMENT = blue, RUNTIME = purple. */
export function ModeBadge({ mode, className }: ModeBadgeProps) {
  return (
    <Badge
      variant="outline"
      className={cn("whitespace-nowrap", MODE_BADGE_CLASSES[mode], className)}
    >
      {mode}
    </Badge>
  );
}

/** Props for {@link TaskRow}. */
export interface TaskRowProps {
  /** The task rendered by this row. */
  task: Task;
}

/**
 * One task rendered as a table row.
 *
 * The title cell holds a real link to the execution trace, so the row is
 * reachable and activatable with the keyboard through normal Tab order
 * rather than a click handler bolted onto `<tr>` (Requirement 9.2). The
 * row keeps a click handler purely as a mouse affordance.
 *
 * Terminal-state tasks show an aggregated result indicator next to the
 * title (check for completed, cross for failure states) with a text
 * equivalent for assistive technology.
 */
export function TaskRow({ task }: TaskRowProps) {
  const router = useRouter();
  const href = `/tasks/${task.task_id}`;

  const navigate = React.useCallback(() => {
    router.push(href);
  }, [router, href]);

  const isTerminal = TERMINAL_STATES.includes(task.state);
  const succeeded = task.state === "completed";

  return (
    <TableRow
      onClick={navigate}
      className="cursor-pointer [&>td]:py-3 md:[&>td]:py-2"
    >
      <TableCell className="max-w-[22rem]">
        <div className="flex items-center gap-2">
          {isTerminal ? (
            succeeded ? (
              <CheckCircle2
                className="h-4 w-4 shrink-0 text-green-600 dark:text-green-400"
                role="img"
                aria-label="Aggregated result: completed"
              />
            ) : (
              <XCircle
                className="h-4 w-4 shrink-0 text-red-600 dark:text-red-400"
                role="img"
                aria-label="Aggregated result: failed"
              />
            )
          ) : null}
          <Link
            href={href}
            onClick={(event) => event.stopPropagation()}
            className="truncate rounded font-medium underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {task.title}
            <span className="sr-only"> — open execution trace</span>
          </Link>
        </div>
      </TableCell>
      <TableCell>
        <StateBadge state={task.state} />
      </TableCell>
      <TableCell>
        <ModeBadge mode={task.mode} />
      </TableCell>
      <TableCell className="font-mono text-xs text-muted-foreground">
        {task.tenant_id}
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
        {formatTimestamp(task.created_at)}
      </TableCell>
      <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
        {formatTimestamp(task.updated_at)}
      </TableCell>
    </TableRow>
  );
}
