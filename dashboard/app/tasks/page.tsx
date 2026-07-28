"use client";

/**
 * Task monitoring page.
 *
 * Fetches the task list over REST on mount, hydrates the task store, and
 * subscribes to the `tasks.*` WebSocket topic so state changes stream in
 * without polling.
 *
 * @module app/tasks/page
 */

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { TaskFilters } from "@/components/tasks/task-filters";
import { TaskList } from "@/components/tasks/task-list";
import { getTasks } from "@/lib/api/tasks";
import { getAuthToken } from "@/lib/api/client";
import { useTaskStore } from "@/lib/stores/task-store";
import { TOPICS } from "@/lib/ws/subscriptions";
import { useWebSocket } from "@/hooks/use-websocket";
import type { Task, WSEvent } from "@/types";

/** Page size for the initial task fetch. */
const PAGE_LIMIT = 100;

/** Loading placeholder mirroring the task table layout. */
function TaskListSkeleton() {
  return (
    <div
      className="space-y-3"
      role="status"
      aria-busy="true"
      aria-label="Loading tasks"
    >
      <Skeleton className="h-10 w-full" />
      {Array.from({ length: 8 }).map((_, index) => (
        <Skeleton key={index} className="h-12 w-full" />
      ))}
    </div>
  );
}

/**
 * Narrow a WebSocket payload into a Task when it carries a task_id.
 *
 * Malformed payloads are skipped rather than crashing the view.
 */
function readTaskPayload(payload: Record<string, unknown>): Task | null {
  const taskId = payload["task_id"];
  if (typeof taskId !== "string" || !taskId) return null;
  return payload as unknown as Task;
}

/** Task list page with live streaming updates. */
export default function TasksPage() {
  const setTasks = useTaskStore((state) => state.setTasks);
  const updateTask = useTaskStore((state) => state.updateTask);
  const addTask = useTaskStore((state) => state.addTask);

  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [token, setToken] = React.useState("");

  // The auth cookie is only readable on the client.
  React.useEffect(() => {
    setToken(getAuthToken());
  }, []);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    getTasks(undefined, undefined, { offset: 0, limit: PAGE_LIMIT })
      .then((response) => {
        if (cancelled) return;
        setTasks(response.items);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load tasks");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [setTasks, reloadKey]);

  const handleEvent = React.useCallback(
    (event: WSEvent) => {
      if (!event.topic.startsWith("tasks.")) return;
      const task = readTaskPayload(event.payload);
      if (!task) return;

      if (event.event_type === "task_created") {
        addTask(task);
        return;
      }
      updateTask(task.task_id, task);
    },
    [addTask, updateTask],
  );

  useWebSocket({
    token,
    topics: [TOPICS.TASKS],
    onEvent: handleEvent,
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-xl font-semibold">Tasks</h2>
          <p className="text-sm text-muted-foreground">
            Live task states streamed from the orchestrator.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => setReloadKey((key) => key + 1)}
          disabled={isLoading}
          aria-label="Refresh task list"
          aria-busy={isLoading}
        >
          Refresh
        </Button>
      </div>

      <TaskFilters />

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load tasks: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : isLoading ? (
        <TaskListSkeleton />
      ) : (
        <TaskList />
      )}
    </div>
  );
}
