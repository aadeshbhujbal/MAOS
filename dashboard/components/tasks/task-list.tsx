"use client";

/**
 * Filterable, sortable task table.
 *
 * Reads tasks plus the active filter/sort configuration from the task
 * store and applies the pure `filterTasks` / `sortTasks` utilities before
 * rendering. Column headers toggle sort direction.
 *
 * @module components/tasks/task-list
 */

import * as React from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { TaskRow } from "@/components/tasks/task-row";
import { useTaskStore } from "@/lib/stores/task-store";
import { filterTasks } from "@/lib/utils/filters";
import { sortTasks } from "@/lib/utils/sorting";

/** Sortable and static columns rendered by the task table. */
const COLUMNS: { key: string; label: string; sortable: boolean }[] = [
  { key: "title", label: "Title", sortable: true },
  { key: "state", label: "State", sortable: true },
  { key: "mode", label: "Mode", sortable: false },
  { key: "tenant_id", label: "Tenant", sortable: false },
  { key: "created_at", label: "Created", sortable: true },
  { key: "updated_at", label: "Updated", sortable: true },
];

/**
 * Task table wired to the task store.
 *
 * Displays an empty-state message when no tasks match the active filter.
 */
export function TaskList() {
  const tasks = useTaskStore((state) => state.tasks);
  const filter = useTaskStore((state) => state.filter);
  const sort = useTaskStore((state) => state.sort);
  const setSort = useTaskStore((state) => state.setSort);

  const visibleTasks = React.useMemo(
    () => sortTasks(filterTasks(tasks, filter), sort),
    [tasks, filter, sort],
  );

  const toggleSort = (field: string) => {
    setSort({
      field,
      direction:
        sort.field === field && sort.direction === "desc" ? "asc" : "desc",
    });
  };

  return (
    <div className="rounded-lg border border-border">
      <Table>
        <caption className="sr-only">
          Tasks with state, operating mode, tenant, and lifecycle timestamps
        </caption>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            {COLUMNS.map((column) => {
              const isSorted = sort.field === column.key;
              return (
                <TableHead
                  key={column.key}
                  aria-sort={
                    isSorted
                      ? sort.direction === "asc"
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  {column.sortable ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column.key)}
                      aria-label={`${column.label}, ${
                        isSorted
                          ? `sorted ${
                              sort.direction === "asc"
                                ? "ascending"
                                : "descending"
                            }`
                          : "not sorted"
                      }. Activate to sort ${
                        isSorted && sort.direction === "desc"
                          ? "ascending"
                          : "descending"
                      }.`}
                      className="flex min-h-touch items-center gap-1 rounded uppercase tracking-wide hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:min-h-0"
                    >
                      {column.label}
                      {isSorted ? (
                        sort.direction === "asc" ? (
                          <ArrowUp className="h-3 w-3" aria-hidden="true" />
                        ) : (
                          <ArrowDown className="h-3 w-3" aria-hidden="true" />
                        )
                      ) : null}
                    </button>
                  ) : (
                    column.label
                  )}
                </TableHead>
              );
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {visibleTasks.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <td
                colSpan={COLUMNS.length}
                className="px-3 py-10 text-center text-sm text-muted-foreground"
              >
                {tasks.length === 0
                  ? "No tasks yet. Submitted tasks will appear here in real time."
                  : "No tasks match the current filters."}
              </td>
            </TableRow>
          ) : (
            visibleTasks.map((task) => (
              <TaskRow key={task.task_id} task={task} />
            ))
          )}
        </TableBody>
      </Table>
      {/*
        Live region: tasks stream in over WebSocket, so the visible count
        changes without a user action. Announcing it politely keeps screen
        reader users informed without stealing focus (Requirement 9.2).
      */}
      <p
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="border-t border-border px-3 py-2 text-xs text-muted-foreground"
      >
        Showing {visibleTasks.length} of {tasks.length} tasks
      </p>
    </div>
  );
}
