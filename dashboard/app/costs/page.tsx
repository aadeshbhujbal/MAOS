"use client";

/**
 * Cost and token metering page.
 *
 * Fetches cost records and the aggregated summary over REST, groups them by
 * provider/agent/task with `aggregateCosts`, and subscribes to the `costs.*`
 * WebSocket topic so the token counter for active tasks updates live.
 *
 * @module app/costs/page
 */

import * as React from "react";
import { Coins, Gauge, Radio } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { BudgetIndicator } from "@/components/costs/budget-indicator";
import { CostChart } from "@/components/costs/cost-chart";
import { getAuthToken } from "@/lib/api/client";
import { getCostSummary, getCosts } from "@/lib/api/costs";
import type { CostSummaryResponse, CostTimeRange } from "@/lib/api/costs";
import { getTasks } from "@/lib/api/tasks";
import { aggregateCosts } from "@/lib/utils/cost-aggregation";
import { formatTimestamp } from "@/lib/utils/format";
import { TOPICS } from "@/lib/ws/subscriptions";
import { useWebSocket } from "@/hooks/use-websocket";
import type { CostRecord, Task, WSEvent, WorkUnitState } from "@/types";

/** Selectable preset ranges plus a custom option. */
type RangePreset = "hour" | "24h" | "7d" | "custom";

/** Preset durations in milliseconds. */
const PRESET_DURATION_MS: Record<Exclude<RangePreset, "custom">, number> = {
  hour: 60 * 60 * 1000,
  "24h": 24 * 60 * 60 * 1000,
  "7d": 7 * 24 * 60 * 60 * 1000,
};

/** States considered active for the live token counter. */
const ACTIVE_STATES: WorkUnitState[] = [
  "assigned",
  "in_progress",
  "awaiting_approval",
];

/** Format a USD amount for card display. */
function formatUsd(value: number): string {
  return value.toLocaleString(undefined, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
  });
}

/** Convert an ISO timestamp to the `datetime-local` input format. */
function toLocalInputValue(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate(),
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Narrow a WebSocket payload into a CostRecord when it carries tokens. */
function readCostPayload(payload: Record<string, unknown>): CostRecord | null {
  const taskId = payload["task_id"];
  const tokens = payload["tokens"];
  if (typeof taskId !== "string" || !taskId) return null;
  if (typeof tokens !== "number" || !Number.isFinite(tokens)) return null;
  return {
    record_id: String(payload["record_id"] ?? `${taskId}-${Date.now()}`),
    task_id: taskId,
    agent_id: String(payload["agent_id"] ?? "unknown"),
    tenant_id: String(payload["tenant_id"] ?? "unknown"),
    provider: String(payload["provider"] ?? "unknown"),
    model: String(payload["model"] ?? "unknown"),
    tokens,
    cost_usd: typeof payload["cost_usd"] === "number" ? payload["cost_usd"] : 0,
    timestamp:
      typeof payload["timestamp"] === "string"
        ? payload["timestamp"]
        : new Date().toISOString(),
  };
}

/** Loading placeholder mirroring the cost panel layout. */
function CostsSkeleton() {
  return (
    <div
      className="space-y-4"
      role="status"
      aria-busy="true"
      aria-label="Loading cost data"
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-28 w-full" />
        ))}
      </div>
      <Skeleton className="h-80 w-full" />
    </div>
  );
}

/** Cost metering page with live token streaming. */
export default function CostsPage() {
  const [preset, setPreset] = React.useState<RangePreset>("24h");
  const [customStart, setCustomStart] = React.useState(() =>
    toLocalInputValue(
      new Date(Date.now() - PRESET_DURATION_MS["24h"]).toISOString(),
    ),
  );
  const [customEnd, setCustomEnd] = React.useState(() =>
    toLocalInputValue(new Date().toISOString()),
  );

  const [records, setRecords] = React.useState<CostRecord[]>([]);
  const [liveRecords, setLiveRecords] = React.useState<CostRecord[]>([]);
  const [summary, setSummary] = React.useState<CostSummaryResponse | null>(
    null,
  );
  const [activeTasks, setActiveTasks] = React.useState<Task[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [reloadKey, setReloadKey] = React.useState(0);
  const [token, setToken] = React.useState("");

  // The auth cookie is only readable on the client.
  React.useEffect(() => {
    setToken(getAuthToken());
  }, []);

  const timeRange = React.useMemo<CostTimeRange>(() => {
    if (preset === "custom") {
      const start = customStart ? new Date(customStart) : null;
      const end = customEnd ? new Date(customEnd) : null;
      return {
        start:
          start && !Number.isNaN(start.getTime())
            ? start.toISOString()
            : new Date(Date.now() - PRESET_DURATION_MS["24h"]).toISOString(),
        end:
          end && !Number.isNaN(end.getTime())
            ? end.toISOString()
            : new Date().toISOString(),
      };
    }
    const end = new Date();
    const start = new Date(end.getTime() - PRESET_DURATION_MS[preset]);
    return { start: start.toISOString(), end: end.toISOString() };
  }, [preset, customStart, customEnd]);

  React.useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);

    Promise.all([
      getCosts(timeRange),
      getCostSummary(),
      getTasks({ state: ACTIVE_STATES }, undefined, { offset: 0, limit: 50 }),
    ])
      .then(([costRecords, costSummary, tasks]) => {
        if (cancelled) return;
        setRecords(costRecords);
        setSummary(costSummary);
        setActiveTasks(tasks.items);
        setLiveRecords([]);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error ? err.message : "Failed to load cost data",
        );
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [timeRange, reloadKey]);

  const handleEvent = React.useCallback((event: WSEvent) => {
    if (!event.topic.startsWith("costs.")) return;
    const record = readCostPayload(event.payload);
    if (!record) return;

    setLiveRecords((current) => [...current, record]);
    setActiveTasks((current) =>
      current.map((task) =>
        task.task_id === record.task_id
          ? {
              ...task,
              tokens_consumed: task.tokens_consumed + record.tokens,
            }
          : task,
      ),
    );
  }, []);

  useWebSocket({
    token,
    topics: [TOPICS.COSTS],
    onEvent: handleEvent,
  });

  const allRecords = React.useMemo(
    () => [...records, ...liveRecords],
    [records, liveRecords],
  );

  const byProvider = React.useMemo(
    () =>
      aggregateCosts(allRecords, "provider").sort(
        (a, b) => b.total_tokens - a.total_tokens,
      ),
    [allRecords],
  );

  const totals = React.useMemo(() => {
    const liveTokens = liveRecords.reduce((sum, r) => sum + r.tokens, 0);
    const liveCost = liveRecords.reduce((sum, r) => sum + r.cost_usd, 0);
    return {
      tokens: (summary?.total_tokens ?? 0) + liveTokens,
      cost: (summary?.total_cost_usd ?? 0) + liveCost,
      liveTokens,
    };
  }, [summary, liveRecords]);

  const activeTokens = React.useMemo(
    () => activeTasks.reduce((sum, task) => sum + task.tokens_consumed, 0),
    [activeTasks],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Costs</h2>
          <p className="text-sm text-muted-foreground">
            Token consumption and estimated spend, streamed from the metering
            service.
          </p>
        </div>

        <div className="flex flex-wrap items-end gap-2">
          <label className="flex flex-col gap-1 text-xs text-muted-foreground">
            Time range
            <Select
              className="w-44"
              aria-label="Cost time range"
              value={preset}
              onChange={(event) => setPreset(event.target.value as RangePreset)}
            >
              <option value="hour">Last hour</option>
              <option value="24h">Last 24 hours</option>
              <option value="7d">Last 7 days</option>
              <option value="custom">Custom range</option>
            </Select>
          </label>

          {preset === "custom" ? (
            <>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                From
                <Input
                  type="datetime-local"
                  className="w-52"
                  aria-label="From — custom range start"
                  value={customStart}
                  onChange={(event) => setCustomStart(event.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">
                To
                <Input
                  type="datetime-local"
                  className="w-52"
                  aria-label="To — custom range end"
                  value={customEnd}
                  onChange={(event) => setCustomEnd(event.target.value)}
                />
              </label>
            </>
          ) : null}

          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
            disabled={isLoading}
            aria-label="Refresh cost data"
            aria-busy={isLoading}
          >
            Refresh
          </Button>
        </div>
      </div>

      {error ? (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm"
        >
          <span>Could not load cost data: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            Retry
          </Button>
        </div>
      ) : isLoading ? (
        <CostsSkeleton />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Card>
              <CardHeader className="p-4 pb-2">
                <CardDescription className="flex items-center gap-2">
                  <Coins className="h-4 w-4" aria-hidden="true" />
                  Total tokens
                </CardDescription>
                <CardTitle className="text-2xl">
                  {totals.tokens.toLocaleString()}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-xs text-muted-foreground">
                {formatTimestamp(timeRange.start)} →{" "}
                {formatTimestamp(timeRange.end)}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="p-4 pb-2">
                <CardDescription className="flex items-center gap-2">
                  <Gauge className="h-4 w-4" aria-hidden="true" />
                  Estimated cost
                </CardDescription>
                <CardTitle className="text-2xl">
                  {formatUsd(totals.cost)}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-xs text-muted-foreground">
                {byProvider.length} provider
                {byProvider.length === 1 ? "" : "s"} reporting
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="p-4 pb-2">
                <CardDescription className="flex items-center gap-2">
                  <Radio className="h-4 w-4" aria-hidden="true" />
                  Active task tokens
                </CardDescription>
                <CardTitle
                  className="text-2xl"
                  aria-live="polite"
                  aria-atomic="true"
                >
                  {activeTokens.toLocaleString()}
                </CardTitle>
              </CardHeader>
              <CardContent className="p-4 pt-0 text-xs text-muted-foreground">
                {activeTasks.length} active task
                {activeTasks.length === 1 ? "" : "s"} · +
                {totals.liveTokens.toLocaleString()} streamed this session
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="p-4 pb-0">
              <CardTitle className="text-base">By provider</CardTitle>
              <CardDescription>
                Token and cost attribution across LLM providers.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-4">
              {byProvider.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No provider costs recorded for this range.
                </p>
              ) : (
                <ul className="flex flex-wrap gap-2">
                  {byProvider.map((entry) => (
                    <li key={entry.key}>
                      <Badge variant="outline" className="gap-2 py-1">
                        <span className="font-semibold">{entry.key}</span>
                        <span className="font-mono text-[11px] text-muted-foreground">
                          {entry.total_tokens.toLocaleString()} tok ·{" "}
                          {formatUsd(entry.total_cost_usd)}
                        </span>
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="p-4 pb-0">
              <CardTitle className="text-base">
                Token consumption over time
              </CardTitle>
              <CardDescription>
                One line per provider, downsampled to 500 points per series.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-4">
              <CostChart records={allRecords} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="p-4 pb-0">
              <CardTitle className="text-base">Active task budgets</CardTitle>
              <CardDescription>
                Warning shown once a task passes 80% of its token budget.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 p-4">
              {activeTasks.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No active tasks are consuming tokens right now.
                </p>
              ) : (
                activeTasks.map((task) => (
                  <BudgetIndicator
                    key={task.task_id}
                    label={task.title}
                    consumed={task.tokens_consumed}
                    budget={task.token_budget}
                  />
                ))
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
