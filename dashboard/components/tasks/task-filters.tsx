"use client";

/**
 * Filter controls for the task list.
 *
 * State is a multi-select (toggle chips), mode is a single select, and
 * tenant is free text. Every change writes the merged filter back into
 * the task store, which the task table reads.
 *
 * @module components/tasks/task-filters
 */

import * as React from "react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { stateBadgeClass } from "@/components/tasks/task-row";
import { useTaskStore } from "@/lib/stores/task-store";
import type { OperatingMode, WorkUnitState } from "@/types";

/** All selectable work unit states, in lifecycle order. */
const STATES: WorkUnitState[] = [
  "assigned",
  "in_progress",
  "awaiting_approval",
  "completed",
  "failed",
  "timed_out",
  "permanently_failed",
];

/** All selectable operating modes. */
const MODES: OperatingMode[] = ["DEVELOPMENT", "RUNTIME"];

/**
 * Task filter panel bound to the task store.
 *
 * @example
 * ```tsx
 * <TaskFilters />
 * ```
 */
export function TaskFilters() {
  const filter = useTaskStore((state) => state.filter);
  const setFilter = useTaskStore((state) => state.setFilter);

  const selectedStates = filter.state ?? [];

  const toggleState = (state: WorkUnitState) => {
    const next = selectedStates.includes(state)
      ? selectedStates.filter((s) => s !== state)
      : [...selectedStates, state];
    setFilter({ ...filter, state: next.length ? next : undefined });
  };

  const handleModeChange = (value: string) => {
    setFilter({
      ...filter,
      mode: value ? [value as OperatingMode] : undefined,
    });
  };

  const handleTenantChange = (value: string) => {
    setFilter({
      ...filter,
      tenant_id: value.trim() ? value.trim() : undefined,
    });
  };

  const hasActiveFilter =
    selectedStates.length > 0 ||
    (filter.mode?.length ?? 0) > 0 ||
    Boolean(filter.tenant_id);

  return (
    <section
      aria-label="Task filters"
      className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4"
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          State
        </legend>
        {/*
          Toggle chips are plain buttons carrying `aria-pressed`, which is
          the standard pattern for a multi-select filter set: each chip
          reports its own pressed state and stays in the natural tab order
          (Requirement 9.2).
        */}
        <div className="flex flex-wrap gap-2">
          {STATES.map((state) => {
            const active = selectedStates.includes(state);
            return (
              <button
                key={state}
                type="button"
                aria-pressed={active}
                onClick={() => toggleState(state)}
                className={cn(
                  "inline-flex min-h-touch items-center rounded-full border px-3 py-0.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background md:min-h-0 md:px-2.5",
                  active
                    ? stateBadgeClass(state)
                    : "border-input text-muted-foreground hover:text-foreground",
                )}
              >
                {state.replace(/_/g, " ")}
              </button>
            );
          })}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label
            htmlFor="task-filter-mode"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Operating mode
          </label>
          <Select
            id="task-filter-mode"
            value={filter.mode?.[0] ?? ""}
            onChange={(event) => handleModeChange(event.target.value)}
          >
            <option value="">All modes</option>
            {MODES.map((mode) => (
              <option key={mode} value={mode}>
                {mode}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex flex-col gap-2">
          <label
            htmlFor="task-filter-tenant"
            className="text-xs font-medium uppercase tracking-wide text-muted-foreground"
          >
            Tenant ID
          </label>
          <Input
            id="task-filter-tenant"
            placeholder="e.g. tenant-acme"
            value={filter.tenant_id ?? ""}
            onChange={(event) => handleTenantChange(event.target.value)}
          />
        </div>
      </div>

      {hasActiveFilter ? (
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setFilter({})}
          >
            Clear filters
          </Button>
        </div>
      ) : null}
    </section>
  );
}
