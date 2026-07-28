"use client";

/**
 * Execution trace timeline for a single task.
 *
 * Fetches the task with its subtask / sub-subtask hierarchy, builds a
 * chronologically ordered timeline with `buildTimeline`, and renders each
 * entry with a type icon, state badge, timestamps, and hierarchy indentation.
 *
 * @module app/tasks/[taskId]/page
 */

import * as React from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  ClipboardList,
  Cpu,
  GitBranch,
  Sparkles,
  Wrench,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ModeBadge, StateBadge } from "@/components/tasks/task-row";
import { getTaskDetail, type TaskDetailResponse } from "@/lib/api/tasks";
import { buildTimeline, type TimelineEntry } from "@/lib/utils/timeline";
import { formatDuration, formatTimestamp } from "@/lib/utils/format";

/** Icon and indentation depth for each timeline entry type. */
const ENTRY_PRESENTATION: Record<
  TimelineEntry["type"],
  {
    icon: React.ComponentType<{ className?: string }>;
    depth: number;
    label: string;
  }
> = {
  task: { icon: ClipboardList, depth: 0, label: "Task" },
  subtask: { icon: GitBranch, depth: 1, label: "Subtask" },
  sub_subtask: { icon: Cpu, depth: 2, label: "Sub-subtask" },
  tool_invocation: { icon: Wrench, depth: 3, label: "Tool invocation" },
  llm_call: { icon: Sparkles, depth: 3, label: "LLM call" },
};

/** Render a single metadata key/value pair as a compact chip. */
function MetadataChip({ label, value }: { label: string; value: string }) {
  return (
    <Badge variant="outline" className="font-mono text-[11px] font-normal">
      {label}: {value}
    </Badge>
  );
}

/** One timeline entry row, indented by hierarchy depth. */
function TimelineRow({ entry }: { entry: TimelineEntry }) {
  const { icon: Icon, depth, label } = ENTRY_PRESENTATION[entry.type];
  const duration = formatDuration(entry.started_at, entry.completed_at);
  const isSensitive = entry.metadata["is_sensitive"] === true;
  const awaitingApproval = entry.state === "awaiting_approval";

  return (
    <li className="relative" style={{ marginLeft: `${depth * 1.5}rem` }}>
      <div
        className={cn(
          "flex flex-col gap-2 rounded-lg border border-border bg-card p-3",
          awaitingApproval && "border-yellow-500/50",
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Icon
            className="h-4 w-4 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <span className="text-xs uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          <span className="min-w-0 truncate font-medium">{entry.label}</span>
          <span className="ml-auto flex items-center">
            <span className="sr-only">State:</span>
            <StateBadge state={entry.state} />
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>Started {formatTimestamp(entry.started_at)}</span>
          <span>
            {entry.completed_at
              ? `Completed ${formatTimestamp(entry.completed_at)}`
              : "In flight"}
          </span>
          {duration ? <span>Duration {duration}</span> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          {Object.entries(entry.metadata)
            .filter(([, value]) => value !== undefined && value !== null)
            .map(([key, value]) => (
              <MetadataChip key={key} label={key} value={String(value)} />
            ))}
          {isSensitive ? (
            <Badge
              variant="outline"
              className="border-orange-500/40 bg-orange-500/15 text-[11px] text-orange-800 dark:text-orange-300"
            >
              sensitive
            </Badge>
          ) : null}
          {awaitingApproval ? (
            <Badge
              variant="outline"
              className="border-yellow-500/40 bg-yellow-500/15 text-[11px] text-yellow-800 dark:text-yellow-300"
            >
              <AlertTriangle className="mr-1 h-3 w-3" aria-hidden="true" />
              awaiting human approval
            </Badge>
          ) : null}
        </div>
      </div>
    </li>
  );
}

/** Loading placeholder for the trace view. */
function TraceSkeleton() {
  return (
    <div
      className="space-y-3"
      role="status"
      aria-busy="true"
      aria-label="Loading execution trace"
    >
      <Skeleton className="h-24 w-full" />
      {Array.from({ length: 5 }).map((_, index) => (
        <Skeleton key={index} className="h-20 w-full" />
      ))}
    </div>
  );
}

/** Execution trace page for a single task. */
export default function TaskTracePage({
  params,
}: {
  params: { taskId: string };
}) {
  const { taskId } = params;
  const [detail, setDetail] = React.useState<TaskDetailResponse | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    getTaskDetail(taskId)
      .then((response) => {
        if (!cancelled) setDetail(response);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load execution trace",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [taskId, reloadKey]);

  const timeline = React.useMemo(() => {
    if (!detail) return [];
    return buildTimeline(
      detail.task,
      detail.subtasks ?? [],
      detail.subSubtasks ?? [],
    );
  }, [detail]);

  return (
    <div className="space-y-4">
      <Link
        href="/tasks"
        className="inline-flex items-center gap-1 rounded text-sm text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to tasks
      </Link>

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load execution trace: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : isLoading ? (
        <TraceSkeleton />
      ) : detail ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="flex flex-wrap items-center gap-2">
                <span className="min-w-0 truncate">{detail.task.title}</span>
                <StateBadge state={detail.task.state} />
                <ModeBadge mode={detail.task.mode} />
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-muted-foreground">
              <p>{detail.task.description}</p>
              <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                <span className="font-mono">task: {detail.task.task_id}</span>
                <span className="font-mono">
                  tenant: {detail.task.tenant_id}
                </span>
                <span>
                  tokens: {detail.task.tokens_consumed} /{" "}
                  {detail.task.token_budget}
                </span>
                <span>Created {formatTimestamp(detail.task.created_at)}</span>
                <span>Updated {formatTimestamp(detail.task.updated_at)}</span>
              </div>
            </CardContent>
          </Card>

          <section aria-label="Execution timeline" className="space-y-2">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
              Execution timeline
            </h2>
            {timeline.length === 0 ? (
              <p className="rounded-lg border border-border px-4 py-10 text-center text-sm text-muted-foreground">
                No timeline entries recorded for this task yet.
              </p>
            ) : (
              <ol className="space-y-2">
                {timeline.map((entry) => (
                  <TimelineRow
                    key={`${entry.type}-${entry.id}`}
                    entry={entry}
                  />
                ))}
              </ol>
            )}
          </section>
        </>
      ) : (
        <p className="rounded-lg border border-border px-4 py-10 text-center text-sm text-muted-foreground">
          Task not found.{" "}
          <Link href="/tasks" className="underline">
            Return to the task list
          </Link>
          .
        </p>
      )}
    </div>
  );
}
